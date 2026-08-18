"""The file-import flow: picker, upload, preview, run, summary dialogs.

One mixin of ``TransactionsPanel`` - state contract in ``base``.
"""

from __future__ import annotations

from uuid import uuid4

import flet as ft

from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.form_fields import (
    FormDropdown,
    FormTextField,
)
from app.components.frontend.controls.loading_overlay import LoadingOverlay
from app.components.frontend.controls.snack_bar import ErrorSnackBar
from app.components.frontend.dashboard.modals.finance_modal.constants import (
    _NEW_ACCOUNT_KEY,
)
from app.components.frontend.dashboard.modals.finance_modal.import_preview import (
    import_preview_body,
)
from app.components.frontend.dashboard.modals.finance_modal.import_summary import (
    _suggested_account_name,
    import_identical_body,
    import_summary_body,
    investment_import_preview_body,
    investment_import_summary_body,
    investment_target_options,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.base import (
    TransactionsPanelState,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.config import settings
from app.core.constants import dashboard_upload_dir


# Import uploads parse the file and run the reconciliation plan inside
# the request, so they legitimately outlive the client-wide 10s UI
# budget. The commit path is exempt: it returns a job id immediately
# and streams progress over SSE.
_IMPORT_TIMEOUT_SECONDS = 120.0

class ImportsFlowMixin(TransactionsPanelState):
    """The file-import flow: picker, upload, preview, run, summary dialogs."""

    # -- File import (OFX/QFX/QIF/CSV, or a custodian ledger for a
    #    brokerage account) --------------------------------------------

    async def open_transactions_import_picker(self) -> None:
        """Open the browser file dialog for a register (bank/card) import.

        Public: the sidebar's Import menu, "Transactions" item.
        """
        await self._open_import_picker(investments=False)

    async def open_investments_import_picker(self) -> None:
        """Open the browser file dialog for an investment-ledger import.

        Public: the sidebar's Import menu, "Investments" item. No
        preconditions: the target account is chosen (or created) in the
        review dialog AFTER the file is parsed, the same order the
        register import works in - file first, decisions second.
        """
        await self._open_import_picker(investments=True)

    async def _open_import_picker(self, *, investments: bool) -> None:
        if self._pending_upload is not None:
            return  # an import is already in flight
        self._import_is_investment = investments
        if investments:
            self._file_picker.pick_files(
                dialog_title="Import investment activity",
                allow_multiple=False,
                allowed_extensions=["csv", "tsv", "txt"],
            )
        else:
            self._file_picker.pick_files(
                dialog_title="Import transactions",
                allow_multiple=False,
                allowed_extensions=["ofx", "qfx", "qif", "csv"],
            )

    def _on_import_picked(self, event: ft.FilePickerResultEvent) -> None:
        if not event.files:
            return  # dialog cancelled
        picked = event.files[0]
        name = picked.name or "upload"
        extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if (
            extension == "qif"
            and self._account is None
            and not self._import_is_investment
        ):
            # QIF carries no account info; fail before the round trip with
            # an instruction instead of a server 400 the client cannot read.
            ErrorSnackBar(
                "Select an account in the sidebar first. QIF files do not "
                "name their account."
            ).launch(self.page)
            return
        # Unique server-side name so concurrent sessions cannot collide
        # (uuid4().hex has no dashes, so split on the first dash recovers
        # the original file name later).
        self._pending_upload = f"{uuid4().hex}-{name}"
        upload_url = self._import_upload_url(self._pending_upload)
        # Block the page for the whole upload+import; cleared by
        # _finish_import (success) or fail() (any error).
        LoadingOverlay.of(self.page).show(f"Uploading {name}...")
        self._file_picker.upload([ft.FilePickerUploadFile(name, upload_url=upload_url)])

    def _import_upload_url(self, server_name: str) -> str:
        """Signed URL for the dashboard-mounted flet upload endpoint.

        ``page.get_upload_url`` cannot be used here: the Flet app is
        mounted at ``/dashboard``, so flet would sign its sub-app-relative
        endpoint while the server verifies the externally visible path
        (``request.url.path`` includes the mount prefix). Signing the
        external path directly satisfies both the route and the check.
        """
        from flet_web.uploads import build_upload_url

        return build_upload_url(
            "/dashboard/upload", server_name, 600, settings.SECRET_KEY
        )

    def _on_import_progress(self, event: ft.FilePickerUploadEvent) -> None:
        if event.error:
            self._pending_upload = None
            LoadingOverlay.of(self.page).fail(
                f"Upload failed: {event.error}", title="Import failed"
            )
            return
        if (event.progress or 0) >= 1.0:
            self.page.run_task(self._finish_import)

    async def _finish_import(self) -> None:
        """Hand the uploaded file to the import API, report, and refresh."""
        from app.components.frontend.state.session_state import get_session_state

        overlay = LoadingOverlay.of(self.page)
        pending, self._pending_upload = self._pending_upload, None
        if pending is None:
            return
        upload_path = dashboard_upload_dir() / pending
        try:
            data = upload_path.read_bytes()
        except OSError:
            overlay.fail(
                "Upload failed: file did not arrive on the server.",
                title="Import failed",
            )
            return
        finally:
            upload_path.unlink(missing_ok=True)

        original_name = pending.split("-", 1)[1]
        if self._import_is_investment:
            await self._finish_investment_import(data, original_name)
            return

        # Classify first, commit second. The preview endpoint runs the SAME
        # plan the import executes, so the review dialog shows exactly what
        # pressing Import will do - and until then nothing is written.
        overlay.update_label(f"Checking {original_name}...")
        params: dict[str, object] = {}
        if self._account is not None:
            params["account_id"] = self._account["id"]
        api = get_session_state(self.page).api_client
        preview = await api.post_multipart(
            "/api/v1/finance/import/preview",
            files={"file": (original_name, data, "application/octet-stream")},
            params=params,
            timeout=_IMPORT_TIMEOUT_SECONDS,
        )
        if not isinstance(preview, dict):
            # Show the real reason (HTTP status + detail body), not a
            # guess - that is the whole point of the overlay.
            overlay.fail(
                api.last_error or "Import failed for an unknown reason.",
                title="Import failed",
            )
            return
        overlay.hide()
        await self._show_import_preview(preview, data, original_name)

    async def _finish_investment_import(self, data: bytes, original_name: str) -> None:
        """Parse-preview the ledger, then open the review dialog where the
        target account is chosen (or created). Mirrors the register
        import's order - classify first, commit second - so nothing is
        written until the dialog's Import button."""
        from app.components.frontend.state.session_state import get_session_state

        overlay = LoadingOverlay.of(self.page)
        overlay.update_label(f"Checking {original_name}...")
        api = get_session_state(self.page).api_client
        preview = await api.post_multipart(
            "/api/v1/finance/import-investments/preview",
            files={"file": (original_name, data, "application/octet-stream")},
            timeout=_IMPORT_TIMEOUT_SECONDS,
        )
        if not isinstance(preview, dict):
            overlay.fail(
                api.last_error or "Import failed for an unknown reason.",
                title="Import failed",
            )
            return
        accounts = await api.get("/api/v1/finance/accounts", cache_ttl=30)
        account_rows = accounts.get("items", []) if isinstance(accounts, dict) else []
        overlay.hide()
        await self._show_investment_import_review(
            preview, account_rows, data, original_name
        )

    async def _show_investment_import_review(
        self,
        preview: dict,
        accounts: list[dict],
        data: bytes,
        original_name: str,
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
            await self._run_investment_import(data, original_name, params)

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

    async def _run_investment_import(
        self, data: bytes, original_name: str, params: dict[str, object]
    ) -> None:
        """Commit a reviewed ledger. Synchronous, no background job - a
        few hundred rows loads in well under a second, unlike a
        multi-year bank statement."""
        from app.components.frontend.state.session_state import get_session_state

        overlay = LoadingOverlay.of(self.page)
        overlay.show(f"Importing {original_name}...")
        api = get_session_state(self.page).api_client
        response = await api.post_multipart(
            "/api/v1/finance/import-investments",
            files={"file": (original_name, data, "application/octet-stream")},
            params=params,
            timeout=_IMPORT_TIMEOUT_SECONDS,
        )
        if not isinstance(response, dict):
            overlay.fail(
                api.last_error or "Import failed for an unknown reason.",
                title="Import failed",
            )
            return
        overlay.hide()
        await self._show_investment_import_summary(response)

        # The target may be a freshly minted account: refresh the sidebar
        # onto it, and this panel's own view if it's the one showing.
        target_id = response.get("account_id")
        if self._account is not None and self._account.get("id") == target_id:
            await self._load_holdings()
        if self._reload_accounts is not None:
            await self._reload_accounts(target_id)

    async def _show_investment_import_summary(self, response: dict) -> None:
        """Modal breakdown of an investment-ledger import; dismissed by OK."""
        dialog: StyledAlertDialog | None = None

        async def _close() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        dialog = StyledAlertDialog(
            title="Import complete",
            body=investment_import_summary_body(response),
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="OK",
                    variant="teal",
                    compact=True,
                )
            ],
            width=500,
        )
        self.page.open(dialog)

    async def _run_import(self, data: bytes, original_name: str) -> None:
        """Commit a previewed file: the background import job path."""
        from app.components.frontend.state.session_state import get_session_state

        overlay = LoadingOverlay.of(self.page)
        overlay.show(f"Importing {original_name}...")
        params: dict[str, object] = {"background": "true"}
        if self._account is not None:
            params["account_id"] = self._account["id"]
        else:
            params.update(self._account_filter.params())
        api = get_session_state(self.page).api_client
        # The endpoint validates the upload and returns a job id in
        # milliseconds; the long part (row inserts + reconciliation rules)
        # runs as a server job whose SSE stream drives this overlay. No
        # request is left holding a multi-minute connection.
        started = await api.post_multipart(
            "/api/v1/finance/import",
            files={"file": (original_name, data, "application/octet-stream")},
            params=params,
        )
        if not isinstance(started, dict) or "job_id" not in started:
            overlay.fail(
                api.last_error or "Import failed for an unknown reason.",
                title="Import failed",
            )
            return
        response = await overlay.run_job(api, started["job_id"], title="Import failed")
        if response is None:
            return  # run_job already showed the job's error

        overlay.hide()
        # An import moves real money around: the outcome gets a modal the
        # user has to acknowledge, not a snackbar that fades while they are
        # looking elsewhere. Every row is accounted for - the counts sum to
        # the file's row total, so nothing vanished silently.
        await self._show_import_summary(response)

        # Balances and the register both moved; refresh panel + sidebar.
        await self._load()
        if self._reload_accounts is not None:
            account_id = self._account["id"] if self._account is not None else None
            await self._reload_accounts(account_id)

    async def _show_import_preview(
        self, preview: dict, data: bytes, original_name: str
    ) -> None:
        """The pre-commit review: what this file will do, before it does it.

        Import commits the very bytes just previewed (the batch dedup ties
        the two requests together by file hash); Cancel writes nothing.
        """
        dialog: StyledAlertDialog | None = None

        async def _close() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        if preview.get("identical_batch_id") is not None:
            dialog = StyledAlertDialog(
                title="Nothing to import",
                body=import_identical_body(preview, original_name),
                actions=[
                    PulseButton(
                        on_click_callable=_close,
                        text="OK",
                        variant="teal",
                        compact=True,
                    )
                ],
                width=520,
            )
            self.page.open(dialog)
            return

        inserted = preview.get("rows_inserted", 0)
        updated = preview.get("rows_updated", 0)
        body = import_preview_body(preview, original_name)

        async def _confirm() -> None:
            await _close()
            await self._run_import(data, original_name)

        changes = inserted + updated
        plural_changes = "s" if changes != 1 else ""
        import_label = (
            f"Import {changes:,} change{plural_changes}" if changes else "Import"
        )
        dialog = StyledAlertDialog(
            title="Review import",
            body=body,
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_confirm,
                    text=import_label,
                    variant="teal",
                    compact=True,
                ),
            ],
            # Three metric cards need the room; 640 squeezed "Already have"
            # onto two lines.
            width=700,
        )
        self.page.open(dialog)

    async def _show_import_summary(self, response: dict) -> None:
        """Modal breakdown of an import; dismissed by OK."""
        dialog: StyledAlertDialog | None = None

        async def _close() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        dialog = StyledAlertDialog(
            title="Import complete",
            body=import_summary_body(response),
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="OK",
                    variant="teal",
                    compact=True,
                )
            ],
            # Matches the review dialog it echoes: same three cards, so
            # the same room, so the two screens line up.
            width=700,
        )
        self.page.open(dialog)
