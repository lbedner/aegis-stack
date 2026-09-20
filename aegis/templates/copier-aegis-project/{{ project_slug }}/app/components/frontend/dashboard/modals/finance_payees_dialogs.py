"""Renaming a payee, and folding several into one."""

from collections.abc import Awaitable, Callable
from typing import Any

import flet as ft

from app.components.frontend.controls import SecondaryText
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.form_fields import FormTextField
from app.components.frontend.controls.provider_icon import ProviderIcon
from app.components.frontend.controls.snack_bar import (
    ErrorSnackBar,
    SuccessSnackBar,
)
from app.components.frontend.controls.table import TableNameText
from app.components.frontend.dashboard.modals.finance_modal.formatting import _usd
from app.components.frontend.theme import AegisTheme as Theme

_MERCHANTS_URL = "/api/v1/finance/merchants"


class PayeeDialogsMixin:
    """The two dialogs the payees tab opens, and the writes behind them.

    Everything they touch is set up by ``PayeesTab.__init__``; the
    attributes and the reload are declared so this module type checks
    on its own.
    """

    page: ft.Page
    _items: list[dict[str, Any]]
    _selected_ids: set[int]
    _load: Callable[[], Awaitable[None]]

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
