""" "Make recurring" from selected rows: preview, dialog, declare, follow-up offer.

One mixin of ``TransactionsPanel`` - state contract in ``base``.
"""

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
from app.components.frontend.controls.form_fields import (
    FormDropdown,
    FormTextField,
)
from app.components.frontend.controls.pickers import CategoryPickerField
from app.components.frontend.controls.snack_bar import (
    ErrorSnackBar,
    SuccessSnackBar,
)
from app.components.frontend.controls.table import TableNameText
from app.components.frontend.dashboard.modals.finance_modal.constants import (
    _DECLARE_GROUP_CHROME,
    _DENSE_ROW_HEIGHT,
    _FREQUENCY_LABELS,
)
from app.components.frontend.dashboard.modals.finance_modal.curation_shared import (
    _declare_body_height,
    _group_table_height,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    _amount_cell,
    _frequency_label,
    _parse_dollars,
    _usd,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.base import (
    TransactionsPanelState,
)
from app.components.frontend.dashboard.modals.modal_sections import date_cell
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_date


class DeclareMixin(TransactionsPanelState):
    """ "Make recurring" from selected rows: preview, dialog, declare, follow-up offer."""

    async def _preview_recurring(self, transaction_ids: list[int]) -> None:
        """Ask the server what this would do, then show it.

        A preview round trip rather than a plain "are you sure": the write
        is not confined to the rows that were ticked (it sweeps in every
        sibling of the same payee and folds away whatever already described
        the bill), and neither of those is guessable from the selection.
        """
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        plan = await api.post(
            "/api/v1/finance/transactions/declare-recurring/preview",
            json={"transaction_ids": transaction_ids},
        )
        groups = plan.get("items", []) if isinstance(plan, dict) else []
        if not groups:
            ErrorSnackBar(
                "Nothing to make recurring. Transfers and pending rows cannot be bills."
            ).launch(self.page)
            return
        self._open_recurring_dialog(transaction_ids, groups)

    def _open_recurring_dialog(
        self, transaction_ids: list[int], groups: list[dict]
    ) -> None:
        name_fields: dict[str, FormTextField] = {}
        amount_fields: dict[str, FormTextField] = {}
        category_fields: dict[str, CategoryPickerField] = {}
        frequency_fields: dict[str, FormDropdown] = {}
        # Rows unticked in the member tables, accumulated across groups.
        # Starts empty: everything the sweep found is in the bill until
        # the user says otherwise.
        excluded: set[int] = set()
        sections: list[ft.Control] = []
        for group in groups:
            key = group.get("key", "")
            members = group.get("members", [])
            rolled = group.get("occurrence_count", 0)
            picked = group.get("selected_count", 0)
            # 320 + 140 + 260 + two MD gaps fits inside the 820 dialog's
            # padded content; the old 360/140/300 row clipped its last
            # field at the dialog edge.
            field = FormTextField(
                label="Bill name",
                value=group.get("name", ""),
                width=320,
            )
            name_fields[key] = field
            # Prefilled from what you TICKED, not the sweep's median: one
            # bank descriptor can cover $500 and $16,320, and only the row
            # you picked is a figure you can vouch for. Stating it pins
            # the bill fixed-amount instead of "varies".
            amount_field = FormTextField(
                label="Amount ($)",
                value=f"{(group.get('selected_amount') or 0) / 100:.2f}",
                width=140,
            )
            amount_fields[key] = amount_field
            # The bill's category, set at the same time as its name. On
            # the STREAM only - the transactions rolling in keep theirs.
            category_dd = CategoryPickerField(
                categories=self._categories,
                width=260,
            )
            category_fields[key] = category_dd
            # The cadence, because measuring it only works for the six
            # canonical gaps detection knows. A semiannual premium is not
            # one of them: it measures as "irregular", which the forecast
            # cannot step, so the bill never reaches the projection at all.
            #
            # The default KEEPS whatever was measured (empty value, sent as
            # nothing), because ``FormDropdown`` falls back to its first
            # option otherwise - silently declaring a yearly premium weekly
            # is a worse failure than leaving it as it was.
            measured = group.get("frequency", "")
            keep_label = _frequency_label(measured)
            if measured not in _FREQUENCY_LABELS:
                keep_label += " (will not forecast)"
            frequency_dd = FormDropdown(
                label="Frequency",
                options=[("", keep_label), *_FREQUENCY_LABELS.items()],
                value="",
                width=200,
            )
            frequency_fields[key] = frequency_dd
            # What the cadence maths concluded, in the same line as the
            # roll-up count: those two together are the claim being made.
            facts = [
                _frequency_label(group.get("frequency", "")),
                _usd(-group.get("average_amount", 0))
                if group.get("direction") == "outflow"
                else _usd(group.get("average_amount", 0)),
            ]
            if group.get("amount_is_variable"):
                facts.append("amount varies")
            if group.get("next_expected_date"):
                facts.append(f"next {format_date(group['next_expected_date'])}")
            if group.get("account_name"):
                facts.append(str(group["account_name"]))
            # Wraps: four fields do not fit the 820 panel's padded width,
            # so name/amount/frequency take the first line and category
            # the second rather than the last field clipping at the edge.
            sections.append(
                ft.Row(
                    [field, amount_field, frequency_dd, category_dd],
                    spacing=Theme.Spacing.MD,
                    run_spacing=Theme.Spacing.SM,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.END,
                )
            )
            sections.append(SecondaryText("  ·  ".join(f for f in facts if f)))
            # The sweep, stated plainly. "13 transactions roll up (you
            # picked 2)" is the surprise worth naming before it happens.
            summary = f"{rolled:,} transaction{'s' if rolled != 1 else ''} roll up"
            if picked and picked != rolled:
                summary += f" (you picked {picked:,})"
            absorbs = group.get("absorbs") or []
            if absorbs:
                summary += f". Folds in: {', '.join(absorbs)}"
            sections.append(SecondaryText(summary))
            # A payee that really does sell you two things gets two bills.
            # Worth saying out loud, because the alternative reading - that
            # this is about to overwrite the bill already there - is the
            # scarier one.
            if group.get("creates_new_bill"):
                sections.append(
                    SecondaryText(
                        "Separate bill. "
                        f"{group.get('existing_bill_name') or 'An existing bill'} "
                        "keeps its own transactions.",
                        color=Theme.Colors.ACCENT,
                    )
                )
            sections.append(
                SecondaryText("Untick anything that is not part of this bill.")
            )

            def _on_member_toggle(indices: set[int], _members: list = members) -> None:
                # Inverted on purpose: the table reports what is CHECKED,
                # and this dialog cares about what is not.
                for position, member in enumerate(_members):
                    member_id = member.get("id")
                    if member_id is None:
                        continue
                    if position in indices:
                        excluded.discard(member_id)
                    else:
                        excluded.add(member_id)

            sections.append(
                DataTable(
                    columns=[
                        DataTableColumn("Date", width=120),
                        DataTableColumn("Description", hideable=False),
                        DataTableColumn("Amount", width=120, alignment="right"),
                    ],
                    rows=[
                        [
                            date_cell(m.get("date")),
                            TableNameText(m.get("name", "")),
                            _amount_cell(m.get("amount", 0)),
                        ]
                        for m in members
                    ],
                    row_padding=6,
                    item_extent=_DENSE_ROW_HEIGHT,
                    scroll_height=_group_table_height(
                        len(members),
                        getattr(self.page, "height", None),
                        tables=len(groups),
                        table_chrome=_DECLARE_GROUP_CHROME,
                    ),
                    selectable=True,
                    selected_indices=list(range(len(members))),
                    on_selection_change=_on_member_toggle,
                )
            )

        async def _close() -> None:
            dialog.open = False
            self.page.update()

        async def _confirm() -> None:
            names = {
                key: (field.value or "").strip()
                for key, field in name_fields.items()
                if (field.value or "").strip()
            }
            if len(names) != len(name_fields):
                ErrorSnackBar("Give every bill a name.").launch(self.page)
                return
            picked = {
                key: int(control.value)
                for key, control in category_fields.items()
                if control.value
            }
            stated = {
                key: cents
                for key, control in amount_fields.items()
                if (cents := _parse_dollars(control.value or "")) > 0
            }
            # Empty means "keep what was measured", so it is not sent.
            cadences = {
                key: control.value
                for key, control in frequency_fields.items()
                if control.value
            }
            dialog.open = False
            self.page.update()
            await self._declare_recurring(
                transaction_ids, names, sorted(excluded), picked, stated, cadences
            )

        total = sum(g.get("occurrence_count", 0) for g in groups)
        dialog = StyledAlertDialog(
            title="Make recurring" if len(groups) == 1 else "Make recurring bills",
            body=ft.Container(
                content=ft.Column(
                    sections,
                    spacing=Theme.Spacing.SM,
                    tight=True,
                    scroll=ft.ScrollMode.AUTO,
                ),
                height=_declare_body_height(
                    len(groups),
                    _group_table_height(
                        max((len(g.get("members") or []) for g in groups), default=0),
                        getattr(self.page, "height", None),
                        tables=len(groups),
                        table_chrome=_DECLARE_GROUP_CHROME,
                    ),
                    getattr(self.page, "height", None),
                ),
            ),
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_confirm,
                    text=f"Make recurring ({total:,})",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=820,
        )
        self.page.open(dialog)

    async def _declare_recurring(
        self,
        transaction_ids: list[int],
        names: dict[str, str],
        exclude_transaction_ids: list[int] | None = None,
        categories: dict[str, int] | None = None,
        amounts: dict[str, int] | None = None,
        frequencies: dict[str, str] | None = None,
    ) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.post(
            "/api/v1/finance/transactions/declare-recurring",
            json={
                "transaction_ids": transaction_ids,
                "names": names,
                "exclude_transaction_ids": exclude_transaction_ids or [],
                "categories": categories or {},
                "amounts": amounts or {},
                "frequencies": frequencies or {},
            },
        )
        if not isinstance(result, dict):
            ErrorSnackBar("Could not make that recurring.").launch(self.page)
            return
        streams = result.get("streams", 0)
        matched = result.get("transactions", 0)
        reconciled = result.get("reconciled", 0)
        if not streams:
            ErrorSnackBar(
                "Nothing to make recurring. Transfers and pending rows cannot be bills."
            ).launch(self.page)
            return
        message = (
            f"{streams} recurring "
            f"{'stream' if streams == 1 else 'streams'} from "
            f"{matched} transaction{'s' if matched != 1 else ''}."
        )
        if reconciled:
            message += (
                f" Folded in {reconciled} duplicate{'s' if reconciled != 1 else ''}."
            )
        SuccessSnackBar(message).launch(self.page)
        self._selected_txn_ids.clear()
        self._selected_amount = 0
        await self._load()

    def _category_name_for(self, category_id: int | None) -> str | None:
        if category_id is None:
            return None
        key = str(category_id)
        return next((name for k, name in self._categories if k == key), None)

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
