"""After a declaration: offering the category it implies."""

from __future__ import annotations

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    NativeDropdown,
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.snack_bar import (
    SuccessSnackBar,
)
from app.components.frontend.controls.table import TableNameText
from app.components.frontend.dashboard.modals.finance_modal.constants import (
    _DENSE_ROW_HEIGHT,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    _amount_cell,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.base import (
    TransactionsPanelState,
)
from app.components.frontend.dashboard.modals.modal_sections import date_cell
from app.components.frontend.theme import AegisTheme as Theme


class DeclareFollowupMixin(TransactionsPanelState):
    """The offer that follows a declaration.

    Declaring a stream tells us the payee is worth its own category;
    this asks, once, whether to make it - and only when the answer
    would change anything.
    """

    @staticmethod
    def _category_offer_worth_making(summary: dict) -> bool:
        """Only ask when there's something to settle: the payee's own
        transactions disagree with each other, or some aren't categorized
        at all. A payee whose history already agrees (Google: 21 of 21
        "Bills & Utilities:Streaming") needs no dialog - silently
        re-confirming what's already true is just a click to dismiss."""
        total = summary.get("total", 0)
        if not total:
            return False
        return (
            summary.get("distinct_categories", 0) > 1
            or summary.get("dominant_count", 0) < total
        )

    async def _offer_followup(
        self, api, merchant_id: int, similar: list, summary: dict
    ) -> None:
        """One follow-up after naming a payee, covering both halves of
        "make this stick": the lookalike rows that should carry the same
        payee, and the category they should all share.

        Both are offers, never silent writes - the lookalike match is a
        loose heuristic (FinanceService.similar_unassigned) and the
        category is a judgement only the user can make, which is the same
        reason ``suggest_categories`` computes without applying. One
        dialog rather than two: they're a single decision about one payee,
        and asking twice in a row for one click is worse than asking once.
        """
        items = list(similar)

        # A real DataTable, not a formatted string: the same columns and
        # density as every other transaction list here, so the rows are
        # scannable (and ALL of them are shown, scrolling if need be,
        # rather than the first handful plus "and N more" - the whole
        # point of showing the list is that the match is a heuristic worth
        # checking). Checkboxes start all-on: a wrong lookalike gets
        # unticked rather than forcing all-or-nothing on the whole sweep.
        selected: set[int] = set(range(len(items)))
        columns = [
            DataTableColumn("Date", width=110),
            DataTableColumn("Payee", hideable=False),
            DataTableColumn("Amount", width=130, alignment="right"),
        ]
        rows = [
            [
                date_cell(i.get("date")),
                TableNameText(i.get("name") or ""),
                _amount_cell(i.get("amount", 0)),
            ]
            for i in items
        ]
        apply_button = PulseButton(
            on_click_callable=lambda: _apply_all(),
            text="Apply",
            variant="teal",
            compact=True,
        )

        # -- the category half -------------------------------------------
        # Pre-filled with whatever this payee's own transactions already
        # mostly use, so the common case is one glance and Apply. Ticked by
        # default only because we only get here when something disagrees
        # (see _category_offer_worth_making) - untick and no category is
        # written at all.
        offer_category = self._category_offer_worth_making(summary)
        preselected = summary.get("dominant_category_id") or summary.get(
            "default_category_id"
        )
        category_checkbox = ft.Checkbox(value=True, scale=0.85)
        # A NATIVE searchable dropdown, not this panel's CategoryPickerButton:
        # that one is a page.overlay popup, and a page.overlay popup nested
        # inside a real ft.AlertDialog renders BEHIND it (the exact layering
        # problem OverlayStyledDialog exists for - see base_popup.py). Flet's
        # own Dropdown is a Flutter menu, so it paints above the dialog, and
        # its enable_search covers the 267-category list. The custom picker
        # is still the right call in a table CELL, where this one was far
        # too cramped; a dialog has the room.
        category_dd = NativeDropdown(
            options=[ft.dropdown.Option(key=k, text=t) for k, t in self._categories],
            value=str(preselected) if preselected else None,
            menu_height=260,
        )

        total = summary.get("total", 0)
        dominant = summary.get("dominant_count", 0)
        category_row = ft.Column(
            [
                ft.Row(
                    [
                        category_checkbox,
                        SecondaryText("Also set category to"),
                        category_dd,
                    ],
                    spacing=Theme.Spacing.SM,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                SecondaryText(
                    (
                        f"{dominant} of {total} already use it"
                        + (
                            f" · {summary['distinct_categories']} different "
                            "categories in this payee's history"
                            if summary.get("distinct_categories", 0) > 1
                            else ""
                        )
                    ),
                    size=Theme.Typography.CAPTION,
                ),
            ],
            spacing=2,
            tight=True,
            visible=offer_category,
        )

        def _on_selection(indices: set[int]) -> None:
            selected.clear()
            selected.update(indices)
            _sync_apply_label()

        def _sync_apply_label() -> None:
            apply_button.text = f"Apply to {len(selected)}" if items else "Apply"
            apply_button.disabled = not selected and not (
                offer_category and category_checkbox.value
            )
            if apply_button.page:
                apply_button.update()

        table = DataTable(
            columns=columns,
            rows=rows,
            row_padding=6,
            item_extent=_DENSE_ROW_HEIGHT,
            scroll_height=min(400, 44 + _DENSE_ROW_HEIGHT * len(items)),
            selectable=True,
            selected_indices=selected,
            on_selection_change=_on_selection,
            empty_message="No similar transactions.",
        )

        async def _close() -> None:
            dialog.open = False
            self.page.update()

        async def _apply_all() -> None:
            ids = [items[i]["id"] for i in sorted(selected) if i < len(items)]
            category_id = (
                int(category_dd.value)
                if offer_category and category_checkbox.value and category_dd.value
                else None
            )
            dialog.open = False
            self.page.update()
            if ids:
                # One call does both: the lookalikes get the payee, and
                # (when offered) the category rides along.
                await api.post(
                    "/api/v1/finance/transactions/assign-merchant",
                    json={
                        "transaction_ids": ids,
                        "merchant_id": merchant_id,
                        "category_id": category_id,
                    },
                )
            if category_id is not None:
                # Also settle the rows this payee ALREADY covers - the
                # whole point is that the payee ends up internally
                # consistent, not just the new arrivals.
                existing = await api.get(
                    "/api/v1/finance/transactions",
                    params={"page_size": 500, "merchant_id": merchant_id},
                )
                owned = (
                    [t["id"] for t in existing.get("items", [])]
                    if isinstance(existing, dict)
                    else []
                )
                if owned:
                    await api.post(
                        "/api/v1/finance/transactions/assign-merchant",
                        json={
                            "transaction_ids": owned,
                            "merchant_id": merchant_id,
                            "category_id": category_id,
                        },
                    )
            parts = []
            if ids:
                parts.append(f"payee set on {len(ids)} more")
            if category_id is not None:
                parts.append("category applied and remembered for this payee")
            if parts:
                SuccessSnackBar(f"Done - {', '.join(parts)}.").launch(self.page)
            await self._load()

        blurb = (
            f"{len(items)} other transaction"
            f"{'s' if len(items) != 1 else ''} with no payee look like this "
            "one. Untick anything that isn't a match."
            if items
            else "This payee's transactions aren't all filed the same way."
        )
        dialog = StyledAlertDialog(
            title="Finish setting up this payee",
            body=ft.Column(
                [
                    SecondaryText(blurb),
                    ft.Container(content=table, width=620, visible=bool(items)),
                    category_row,
                ],
                spacing=Theme.Spacing.MD,
                tight=True,
            ),
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                apply_button,
            ],
            width=660,
        )
        self.page.open(dialog)
