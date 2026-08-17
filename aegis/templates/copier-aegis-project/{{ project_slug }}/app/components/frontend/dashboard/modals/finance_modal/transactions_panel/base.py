"""Shared state contract for the transactions-panel mixins.

The panel's 62 methods split across four mixin modules plus the core
panel, all operating on ONE set of state. This base names that state
(and, under ``TYPE_CHECKING``, the cross-module methods), so each mixin
file type-checks on its own and the real definitions win at runtime.

Subclasses ``ft.Container`` so the whole chain sees Flet's own surface
(``page``, ``update``, ``content``) without re-declaring it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import flet as ft

if TYPE_CHECKING:
    from app.components.frontend.controls.buttons import PulseButton
    from app.components.frontend.controls.debounce import Debouncer
    from app.components.frontend.controls.form_fields import FormTextField
    from app.components.frontend.controls.pickers import (
        BulkActionTrigger,
        CategoryPickerButton,
        MerchantPickerButton,
        TagPickerButton,
    )
    from app.components.frontend.controls.text import H3Text, SecondaryText
    from app.components.frontend.dashboard.modals.modal_sections import DateRangeChips


class TransactionsPanelState(ft.Container):  # type: ignore[misc]
    """State every mixin reads; assigned by the panel's ``__init__``."""

    _account: dict[str, Any] | None
    _account_filter: Any
    _account_names: Any
    _body: ft.Container
    _bulk_categorize_trigger: BulkActionTrigger
    _bulk_delete_trigger: BulkActionTrigger
    _bulk_payee_trigger: BulkActionTrigger
    _bulk_recurring_trigger: BulkActionTrigger
    _bulk_tag_trigger: BulkActionTrigger
    _categories: list[tuple[str, str]]
    _category_picker: CategoryPickerButton
    _debounce: Debouncer
    _detail: ft.Container
    _file_picker: ft.FilePicker
    _import_is_investment: bool
    _load_more_link: PulseButton
    _merchant_picker: MerchantPickerButton
    _merchants: list[tuple[str, str]]
    _pending_upload: Any
    _query: str
    _range: DateRangeChips
    _range_days: int
    _register_page_size: Any
    _register_scope: Any
    _register_table: Any
    _reload_accounts: Any
    _search: FormTextField
    _selected_amount: int
    _selected_trade_count: int
    _selected_txn_ids: set[int]
    _selection_label: SecondaryText
    _selection_row: ft.Container
    _subtitle: SecondaryText
    _tag_filter: Any
    _tag_filter_chip: ft.Container
    _tag_picker: TagPickerButton
    _tags: list[tuple[str, str]]
    _title: H3Text

    if TYPE_CHECKING:  # the real definitions live on the mixins / panel

        @staticmethod
        def _category_offer_worth_making(*args: Any, **kwargs: Any) -> Any: ...
        def _create_category(self, *args: Any, **kwargs: Any) -> Any: ...
        def _create_merchant(self, *args: Any, **kwargs: Any) -> Any: ...
        def _filter_by_tag(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _load(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _load_holdings(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _offer_followup(self, *args: Any, **kwargs: Any) -> Any: ...
        def _on_import_picked(self, *args: Any, **kwargs: Any) -> Any: ...
        def _on_import_progress(self, *args: Any, **kwargs: Any) -> Any: ...
        def _open_bulk_categorize(self, *args: Any, **kwargs: Any) -> Any: ...
        def _open_bulk_delete(self, *args: Any, **kwargs: Any) -> Any: ...
        def _open_bulk_payee(self, *args: Any, **kwargs: Any) -> Any: ...
        def _open_bulk_recurring(self, *args: Any, **kwargs: Any) -> Any: ...
        def _open_bulk_tag(self, *args: Any, **kwargs: Any) -> Any: ...
        def _open_reconcile(self, *args: Any, **kwargs: Any) -> Any: ...
        def _open_remove(self, *args: Any, **kwargs: Any) -> Any: ...
        def _open_rename(self, *args: Any, **kwargs: Any) -> Any: ...
        def _pick_category(self, *args: Any, **kwargs: Any) -> Any: ...
        def _pick_merchant(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _preview_recurring(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _reload_merchants(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _reload_tags(self, *args: Any, **kwargs: Any) -> Any: ...
        def _remove_tag(self, *args: Any, **kwargs: Any) -> Any: ...
