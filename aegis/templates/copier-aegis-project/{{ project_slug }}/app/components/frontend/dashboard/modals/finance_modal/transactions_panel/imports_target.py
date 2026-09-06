"""Where does this file go: the import flow's target-account dialogs.

A register statement names no account and a custodian ledger names no
brokerage; both ask the user before anything is written. Split from
``imports_flow`` so each mixin fits in a reader's head. The dialogs know
nothing of what happens next: the caller hands them the continuation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import flet as ft

from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.form_fields import FormDropdown, FormTextField
from app.components.frontend.controls.loading_overlay import LoadingOverlay
from app.components.frontend.controls.snack_bar import ErrorSnackBar
from app.components.frontend.controls.text import SecondaryText
from app.components.frontend.dashboard.modals.finance_modal.constants import (
    _NEW_ACCOUNT_KEY,
)
from app.components.frontend.dashboard.modals.finance_modal.import_summary import (
    _suggested_account_name,
    account_target_options,
    investment_import_preview_body,
    investment_target_options,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.base import (
    TransactionsPanelState,
)
from app.components.frontend.theme import AegisTheme as Theme

# Import uploads parse the file and run the reconciliation plan inside
# the request, so they legitimately outlive the client-wide 10s UI
# budget. The commit path is exempt: it returns a job id immediately
# and streams progress over SSE.
_IMPORT_TIMEOUT_SECONDS = 120.0


class ImportTargetMixin(TransactionsPanelState):
    """The two "into which account?" dialogs of the import flow."""

    async def _ask_target_account(
        self,
        preview: dict,
        data: bytes,
        original_name: str,
        then: Callable[..., Awaitable[None]],
    ) -> None:
        """The file names no account and none is selected: ask, then
        preview again with the answer. Explicit beats a server 400 the
        client can only echo, and beats guessing from the sidebar."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        accounts = await api.get("/api/v1/finance/accounts", cache_ttl=30)
        rows = accounts.get("items", []) if isinstance(accounts, dict) else []
        options, default = account_target_options(rows, None)
        if not options:
            ErrorSnackBar("Create an account first; this file names none.").launch(
                self.page
            )
            return
        target_dd = FormDropdown(label="Into account", options=options, value=default)
        layout = preview.get("layout") or "This file"
        dialog: StyledAlertDialog | None = None

        async def _close() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        async def _preview_into() -> None:
            account_id = int(target_dd.value or default)
            await _close()
            overlay = LoadingOverlay.of(self.page)
            overlay.show(f"Checking {original_name}...")
            again = await api.post_multipart(
                "/api/v1/finance/import/preview",
                files={"file": (original_name, data, "application/octet-stream")},
                params={"account_id": account_id},
                timeout=_IMPORT_TIMEOUT_SECONDS,
            )
            if not isinstance(again, dict):
                overlay.fail(
                    api.last_error or "Import failed for an unknown reason.",
                    title="Import failed",
                )
                return
            overlay.hide()
            await then(again, data, original_name, account_id=account_id)

        dialog = StyledAlertDialog(
            title=f"Import {original_name}",
            body=ft.Column(
                [
                    SecondaryText(
                        f"{layout} statements carry no account name. "
                        f"{preview.get('rows_total', 0):,} rows read. "
                        "Which account is this?",
                        size=Theme.Typography.BODY_SMALL,
                    ),
                    target_dd,
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
                PulseButton(
                    on_click_callable=_preview_into,
                    text="Continue",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=480,
        )
        self.page.open(dialog)


    async def _show_investment_import_review(
        self,
        preview: dict,
        accounts: list[dict],
        data: bytes,
        original_name: str,
        commit: Callable[[bytes, str, dict[str, object]], Awaitable[None]],
    ) -> None:
        """The pre-commit review: what the ledger replays to, and where it
        goes - an existing investment account, or one created on the spot
        (the same courtesy OFX ingest extends to unknown accounts)."""
        selected_id = self._account.get("id") if self._account is not None else None
        options, default = investment_target_options(accounts, selected_id)
        name_field = FormTextField(
            label="New account name",
            value=_suggested_account_name(original_name),
        )
        name_host = ft.Container(
            content=name_field, visible=default == _NEW_ACCOUNT_KEY
        )

        def _target_changed(event: ft.ControlEvent) -> None:
            name_host.visible = event.control.value == _NEW_ACCOUNT_KEY
            if name_host.page is not None:
                name_host.update()

        target_dd = FormDropdown(
            label="Into account",
            options=options,
            value=default,
            on_change=_target_changed,
        )
        dialog: StyledAlertDialog | None = None

        async def _close() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        async def _commit() -> None:
            choice = target_dd.value or _NEW_ACCOUNT_KEY
            params: dict[str, object] = {}
            if choice == _NEW_ACCOUNT_KEY:
                name = (name_field.value or "").strip()
                if not name:
                    name_field.set_error("Name the new account.")
                    return
                params["account_name"] = name
            else:
                params["account_id"] = int(choice)
            await _close()
            await commit(data, original_name, params)

        dialog = StyledAlertDialog(
            title=f"Import {original_name}",
            body=ft.Column(
                [
                    investment_import_preview_body(preview),
                    ft.Container(height=Theme.Spacing.SM),
                    target_dd,
                    name_host,
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
                    on_click_callable=_commit,
                    text="Import",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=560,
        )
        self.page.open(dialog)
