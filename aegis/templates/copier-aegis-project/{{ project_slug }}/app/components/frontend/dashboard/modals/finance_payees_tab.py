"""The Payees tab: the directory of who you actually pay.

A payee (``FinanceMerchant``) is the stable identity behind a drifting
bank descriptor, and three things hang off it: the brand icon, the
default category new transactions inherit, and the grouping key recurring
detection uses. All three were editable only as a SIDE EFFECT of naming a
group on the No payee queue, which also re-filed that group's
transactions - so correcting a logo meant moving rows, and a payee whose
backlog was already empty could not be edited at all.

It sits behind the gear beside Categories and Connections for the reason
that tab row exists: it is a curation surface, not a daily read. You open
it when a logo is wrong or a payee needs merging, the same way you open
Categories when pruning the taxonomy.
"""

from typing import Any

import flet as ft

from app.components.frontend.controls import H3Text, SecondaryText
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.data_table import DataTable, DataTableColumn
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.form_fields import FormTextField
from app.components.frontend.controls.provider_icon import ProviderIcon
from app.components.frontend.controls.snack_bar import (
    ErrorSnackBar,
    SuccessSnackBar,
)
from app.components.frontend.controls.table import TableCellText, TableNameText
from app.components.frontend.dashboard.modals.finance_modal.formatting import _usd
from app.components.frontend.dashboard.modals.modal_sections import (
    EmptyStatePlaceholder,
    date_cell,
    headline_stat,
    row_matches,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_date

from .finance_panel import FinancePanel

_MERCHANTS_URL = "/api/v1/finance/merchants"
_TRANSACTIONS_URL = "/api/v1/finance/transactions"
# One page of a payee's ledger. Target alone runs to 1,015 rows here, and
# the table virtualizes but the payload does not.
_PAGE_SIZE = 500
# Matches the register's dense rows, so the two read as one product.
_ROW_HEIGHT = 40


class PayeesTab(FinancePanel):
    """Every payee, with the weight behind it, editable in place."""

    def __init__(
        self,
        page: ft.Page,
        account_filter: Any = None,
        register_filter_listener: Any = None,
    ) -> None:
        super().__init__(page, account_filter, register_filter_listener)
        # Payees are not per-account, but their WEIGHT is: narrowing to a
        # card should show what that card pays, not the global totals.

        self.expand = True
        self.padding = ft.padding.all(Theme.Spacing.LG)
        self._items: list[dict] = []
        self._query = ""
        # The payee being drilled into, or None for the directory itself.
        self._open_payee: dict | None = None
        self._transactions: list[dict] = []
        self._transaction_total = 0
        self._account_names: dict[int, str] = {}
        self._selected_ids: set[int] = set()
        self._body = ft.Container(expand=True)
        self._stats = ft.Row(
            [],
            spacing=Theme.Spacing.LG,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self._merge_button = PulseButton(
            on_click_callable=self._open_merge,
            text="Merge",
            compact=True,
        )
        self._search = FormTextField(
            label="Search payees",
            on_change=self._on_search,
            width=260,
            compact=True,
            clearable=True,
        )
        self.content = ft.Column(
            [
                ft.Row(
                    [
                        ft.Column(
                            [
                                H3Text("Payees"),
                                SecondaryText(
                                    "Who you pay. Sets the logo, the default "
                                    "category, and how bills are grouped"
                                ),
                            ],
                            spacing=2,
                        ),
                        ft.Container(expand=True),
                        self._merge_button,
                        self._search,
                        self._stats,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=Theme.Spacing.LG,
                ),
                self._body,
            ],
            spacing=Theme.Spacing.MD,
            expand=True,
        )

    def did_mount(self) -> None:
        # Override with a prelude: visible=False as a constructor
        # kwarg is inert on this button family (BaseElevatedButton
        # discards **kwargs), so the initial hide has to be an
        # assignment - then the base's mount fetch runs as usual.
        self._merge_button.visible = False
        super().did_mount()

    def _on_search(self, event: ft.ControlEvent) -> None:
        # No debounce: this filters a list already in memory, so there is
        # no request to coalesce and a keystroke costs a re-render.
        self._query = (getattr(event.control, "value", "") or "").strip()
        self._render()

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        data = await api.get(_MERCHANTS_URL, params=self._account_filter.params())
        self._items = data.get("items", []) if isinstance(data, dict) else []
        if not self._account_names:
            accounts = await api.get(
                "/api/v1/finance/accounts", params={"page_size": 200}
            )
            self._account_names = {
                a["id"]: a.get("name", "Account")
                for a in (
                    accounts.get("items", []) if isinstance(accounts, dict) else []
                )
            }
        self._refresh_open_payee()
        # Anything merged away is gone from the list; keeping it checked
        # would arm a second merge against a deleted row.
        live = {m.get("id") for m in self._items}
        self._selected_ids &= {i for i in live if i is not None}
        self._render()

    def _refresh_open_payee(self) -> None:
        """Re-read the drilled-into payee from the freshly loaded list.

        The drill-down keeps a copy so its header can name the payee, and
        that copy is taken once on the way in. After an edit the list
        behind it reloads but the copy does not, so the payee you just
        renamed still shows its old name - and its old icon - directly
        above its own transactions. Confirmed live: renamed "Stop Shop",
        header stayed "Stop Shop" while the rows below read "Stop & Shop".
        """
        if self._open_payee is None:
            return
        payee_id = self._open_payee.get("id")
        # Gone entirely (deleted elsewhere): drop back to the directory
        # rather than strand a header over rows with no owner.
        self._open_payee = next(
            (m for m in self._items if m.get("id") == payee_id), None
        )

    async def _load_transactions(self, merchant: dict) -> None:
        """One payee's ledger. Server-side filter, not a client slice - a
        busy payee is a thousand rows and the register endpoint already
        knows how to narrow by ``merchant_id``."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        self._open_payee = merchant
        self._transactions = []
        self._render()
        data = await api.get(
            _TRANSACTIONS_URL,
            params={"merchant_id": merchant.get("id"), "page_size": _PAGE_SIZE},
        )
        items = data.get("items", []) if isinstance(data, dict) else []
        self._transactions = items
        self._transaction_total = (
            data.get("total", len(items)) if isinstance(data, dict) else len(items)
        )
        self._render()

    async def _back(self) -> None:
        # async because PulseButton awaits its callable - a sync one is
        # awaited and blows up on None.
        self._open_payee = None
        self._transactions = []
        self._render()

    def _filtered(self) -> list[dict]:
        rows = [
            m
            for m in self._items
            if row_matches(
                self._query,
                (
                    m.get("name"),
                    m.get("website_url"),
                    m.get("transaction_count"),
                    _usd(m.get("total_amount")),
                    format_date(m.get("last_date")),
                ),
            )
        ]
        # Busiest first: the payee worth correcting is the one carrying
        # the most transactions, not the one earliest in the alphabet.
        return sorted(rows, key=lambda m: -(m.get("transaction_count") or 0))

    def _render(self) -> None:
        if self._open_payee is not None:
            self._render_payee()
            return
        self._render_directory()

    def _render_payee(self) -> None:
        from .finance_modal import transaction_table

        payee = self._open_payee or {}
        shown = len(self._transactions)
        total = self._transaction_total
        # Says what the page holds vs what the payee has, because the
        # request is capped - a bare "1,015 transactions" over 500 rows
        # would be describing something that is not on screen.
        counted = (
            f"{total:,} transaction{'s' if total != 1 else ''}"
            if shown >= total
            else f"{shown:,} of {total:,} transactions"
        )
        self._stats.controls = []
        if self._stats.page:
            self._stats.update()

        async def _edit() -> None:
            self._open_editor(payee)

        self._body.content = ft.Column(
            [
                ft.Row(
                    [
                        PulseButton(
                            on_click_callable=self._back,
                            text="Back to payees",
                            variant="muted",
                            compact=True,
                        ),
                        ProviderIcon(payee.get("name") or "?", payee.get("icon_b64")),
                        H3Text(payee.get("name") or ""),
                        SecondaryText(counted),
                        ft.Container(expand=True),
                        PulseButton(
                            on_click_callable=_edit,
                            text="Edit payee",
                            compact=True,
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=Theme.Spacing.MD,
                ),
                transaction_table(
                    self._transactions,
                    account_names=self._account_names,
                    expand=True,
                    show_category=True,
                    # The payee is the filter, so the descriptors under it
                    # are the useful column - that drift is why payees
                    # exist in the first place.
                    payee_column=False,
                    empty_message="No transactions for this payee.",
                ),
            ],
            spacing=Theme.Spacing.MD,
            expand=True,
        )
        if self._body.page:
            self._body.update()

    def _update_merge_button(self) -> None:
        count = len(self._selected_ids)
        self._merge_button.text = f"Merge ({count})" if count else "Merge"
        # Two is the minimum that means anything: merging one payee into
        # itself is refused server-side anyway.
        self._merge_button.visible = count >= 2 and self._open_payee is None
        if self._merge_button.page:
            self._merge_button.update()

    def _render_directory(self) -> None:
        rows = self._filtered()
        unused = sum(1 for m in self._items if not m.get("transaction_count"))
        missing = sum(1 for m in self._items if not m.get("website_url"))
        self._stats.controls = [
            headline_stat("Payees", f"{len(self._items):,}", Theme.Colors.TEXT_PRIMARY),
            headline_stat("No address", f"{missing:,}", Theme.Colors.TEXT_PRIMARY),
            headline_stat("Unused", f"{unused:,}", Theme.Colors.TEXT_PRIMARY),
        ]
        if self._stats.page:
            self._stats.update()

        if not rows:
            self._body.content = EmptyStatePlaceholder(
                message=(
                    "No payees yet. Name one from the No payee queue."
                    if not self._items
                    else "No payee matches that search."
                )
            )
            if self._body.page:
                self._body.update()
            return

        def _open(index: int, _rows: list = rows) -> None:
            if self.page:
                self.page.run_task(self._load_transactions, _rows[index])

        def _on_selection(indices: set[int], _rows: list = rows) -> None:
            self._selected_ids = {
                _rows[i]["id"] for i in indices if i < len(_rows) and _rows[i].get("id")
            }
            self._update_merge_button()

        keep_checked = [
            i for i, m in enumerate(rows) if m.get("id") in self._selected_ids
        ]

        self._body.content = DataTable(
            columns=[
                DataTableColumn("Payee", hideable=False),
                DataTableColumn("Website", width=220, style="secondary"),
                DataTableColumn("Transactions", width=130, alignment="right"),
                DataTableColumn("Total", width=140, alignment="right"),
                DataTableColumn("Last seen", width=130),
            ],
            rows=[
                [
                    ft.Row(
                        [
                            ProviderIcon(m.get("name") or "?", m.get("icon_b64")),
                            ft.Container(
                                content=TableNameText(m.get("name") or ""),
                                expand=True,
                            ),
                        ],
                        spacing=Theme.Spacing.SM,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    # An address that was never set is the actionable state
                    # here - the icon is being guessed from the name, which
                    # can miss or land on somebody else's site entirely.
                    TableCellText(m.get("website_url") or "Guessed from name"),
                    TableCellText(f"{m.get('transaction_count') or 0:,}"),
                    TableCellText(_usd(m.get("total_amount"))),
                    date_cell(m.get("last_date")),
                ]
                for m in rows
            ],
            row_padding=6,
            item_extent=_ROW_HEIGHT,
            # expand, not a fixed scroll_height: 520px is ~13 rows, so it
            # ignored however tall the window actually is AND cut the 14th
            # row in half at the bottom edge, which reads as a rendering
            # bug rather than "there is more below". Expanding fills the
            # panel, and the rows virtualize inside it.
            expand=True,
            on_row_click=_open,
            selectable=True,
            selected_indices=keep_checked,
            on_selection_change=_on_selection,
            column_picker=True,
            empty_message="No payees yet.",
        )
        self._update_merge_button()
        if self._body.page:
            self._body.update()

    def _open_editor(self, merchant: dict) -> None:
        name_field = FormTextField(
            label="Payee name", value=merchant.get("name", ""), width=360
        )
        website_field = FormTextField(
            label="Website",
            value=merchant.get("website_url") or "",
            hint="citizensbank.com",
            width=360,
        )

        async def _close() -> None:
            dialog.open = False
            self.page.update()

        async def _save() -> None:
            typed = (name_field.value or "").strip()
            if not typed:
                ErrorSnackBar("Give the payee a name.").launch(self.page)
                return
            dialog.open = False
            self.page.update()
            await self._save(
                merchant, name=typed, website_url=(website_field.value or "").strip()
            )

        dialog = StyledAlertDialog(
            title="Edit payee",
            body=ft.Column(
                [
                    SecondaryText(
                        f"{merchant.get('transaction_count') or 0:,} transactions, "
                        f"{_usd(merchant.get('total_amount'))}."
                    ),
                    SecondaryText(
                        "The address is what the logo is fetched from. Leave "
                        "it blank to guess from the name."
                    ),
                    ft.Container(height=Theme.Spacing.SM),
                    name_field,
                    website_field,
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
                    on_click_callable=_save, text="Save", variant="teal", compact=True
                ),
            ],
            width=460,
        )
        self.page.open(dialog)

    async def _open_merge(self) -> None:
        """Which payee survives is the user's call, not the biggest one's.

        It decides the name every merged transaction ends up under and,
        because merging only fills GAPS, whose website and default
        category are kept. Defaulting silently to the largest would make
        the loser's curation vanish without anyone choosing that.
        """
        chosen = [m for m in self._items if m.get("id") in self._selected_ids]
        if len(chosen) < 2:
            return
        # Busiest first, so the default lands on the payee most likely to
        # be the real one.
        chosen.sort(key=lambda m: -(m.get("transaction_count") or 0))
        moving = sum(m.get("transaction_count") or 0 for m in chosen[1:])
        survivor = {"id": chosen[0].get("id")}

        # A RadioGroup, not hand-synced checkboxes: "which one survives"
        # is exactly one choice, and letting the control enforce that
        # removes a whole class of state bug (two ticked, or none).
        group = ft.RadioGroup(
            value=str(survivor["id"]),
            on_change=lambda e: survivor.__setitem__("id", int(e.control.value)),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Radio(value=str(merchant.get("id"))),
                            ProviderIcon(
                                merchant.get("name") or "?", merchant.get("icon_b64")
                            ),
                            ft.Container(
                                content=TableNameText(merchant.get("name") or ""),
                                expand=True,
                            ),
                            SecondaryText(
                                f"{merchant.get('transaction_count') or 0:,} "
                                "transactions"
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=Theme.Spacing.SM,
                    )
                    for merchant in chosen
                ],
                spacing=Theme.Spacing.XS,
                tight=True,
            ),
        )

        async def _close() -> None:
            dialog.open = False
            self.page.update()

        async def _confirm() -> None:
            dialog.open = False
            self.page.update()
            await self._merge(
                survivor["id"],
                [m.get("id") for m in chosen if m.get("id") != survivor["id"]],
            )

        dialog = StyledAlertDialog(
            title="Merge payees",
            body=ft.Column(
                [
                    SecondaryText("Pick the payee to keep. The rest fold into it."),
                    group,
                    ft.Container(height=Theme.Spacing.SM),
                    SecondaryText(
                        f"About {moving:,} transactions move. Bills follow too. "
                        "A website or default category is only inherited where "
                        "the payee you keep has none."
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
                    on_click_callable=_confirm,
                    text=f"Merge {len(chosen)}",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=560,
        )
        self.page.open(dialog)

    async def _merge(self, target_id: int, source_ids: list[int]) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.post(
            f"{_MERCHANTS_URL}/{target_id}/merge", json={"source_ids": source_ids}
        )
        if not isinstance(result, dict):
            ErrorSnackBar("Could not merge those payees.").launch(self.page)
            return
        moved = result.get("moved", 0)
        SuccessSnackBar(
            f"Merged {result.get('merged', len(source_ids))} payees. "
            f"{moved:,} transaction{'s' if moved != 1 else ''} moved."
        ).launch(self.page)
        self._selected_ids.clear()
        await self._load()

    async def _save(self, merchant: dict, *, name: str, website_url: str) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.patch(
            f"{_MERCHANTS_URL}/{merchant.get('id')}",
            json={"name": name, "website_url": website_url},
        )
        if not isinstance(result, dict):
            ErrorSnackBar("Could not save that payee.").launch(self.page)
            return
        SuccessSnackBar(f'Saved "{result.get("name", name)}".').launch(self.page)
        await self._load()
