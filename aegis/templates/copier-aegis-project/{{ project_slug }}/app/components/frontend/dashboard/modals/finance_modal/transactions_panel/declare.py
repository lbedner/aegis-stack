""" "Make recurring" from selected rows: preview, dialog, declare, follow-up offer.

One mixin of ``TransactionsPanel`` - state contract in ``base``.
"""

from __future__ import annotations

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
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
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.declare_followup import (  # noqa: E501
    DeclareFollowupMixin,
)
from app.components.frontend.dashboard.modals.modal_sections import date_cell
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_date


class DeclareMixin(DeclareFollowupMixin):
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
