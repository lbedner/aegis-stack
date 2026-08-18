"""Shared state contract for the Bills & Income tab mixins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import flet as ft

from app.components.frontend.dashboard.modals.finance_panel import FinancePanel

if TYPE_CHECKING:
    from app.components.frontend.controls import SecondaryText
    from app.components.frontend.controls.buttons import PulseButton
    from app.components.frontend.controls.debounce import Debouncer
    from app.components.frontend.controls.form_fields import FormTextField
    from app.components.frontend.controls.pickers import (
        BulkActionTrigger,
        CategoryPickerButton,
    )
    from app.components.frontend.controls.tabs import PulseTabs
    from app.components.frontend.dashboard.modals.modal_sections import DateRangeChips


class RecurringTabState(FinancePanel):  # type: ignore[misc]
    """State every mixin reads; assigned by the tab's ``__init__``."""

    _account_filter: Any
    _accounts: Any
    _body: ft.Container
    _categories: Any
    _categorize_trigger: BulkActionTrigger
    _category_picker: CategoryPickerButton
    _debounce: Debouncer
    _delete_button: PulseButton
    _holders: Any
    _items: list[dict[str, Any]]
    _monthly: SecondaryText
    _mute_button: PulseButton
    _partitions: Any
    _pause_button: PulseButton
    _progress: ft.ProgressBar
    _query: str
    _range: DateRangeChips
    _range_days: int
    _search: FormTextField
    _selected: set[int]
    _selection_label: SecondaryText
    _subtab_index: int
    _tabs: PulseTabs

    if TYPE_CHECKING:  # real definitions live on the mixins / tab

        def _action(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _bulk_delete(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _bulk_mute(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _bulk_pause(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _load(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _open_add(self, *args: Any, **kwargs: Any) -> Any: ...
        def _open_bulk_categorize(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _open_edit(self, *args: Any, **kwargs: Any) -> Any: ...
        def _open_pause_dialog(self, *args: Any, **kwargs: Any) -> Any: ...
        def _pick_category(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _rescan(self, *args: Any, **kwargs: Any) -> Any: ...
        def _update_selection(self, *args: Any, **kwargs: Any) -> Any: ...
