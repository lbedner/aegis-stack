"""Shared state contract for the budget-panel mixins.

Four sub-tabs (Budget, Outlook via the pager, Goals, Envelopes) render
into one loaded month. This base names the state they share and, under
``TYPE_CHECKING``, the load/render spine they call back into.

Subclasses ``FinancePanel`` (itself an ``ft.Container``) so the whole
chain keeps the panel lifecycle and Flet's own surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import flet as ft

from app.components.frontend.dashboard.modals.finance_panel import FinancePanel

if TYPE_CHECKING:
    from app.components.frontend.controls.form_fields import FormTextField
    from app.components.frontend.controls.tabs import PulseTabs
    from app.components.frontend.dashboard.modals.finance_modal.stat_details import (
        StatDetailPopup,
    )


class BudgetPanelState(FinancePanel):  # type: ignore[misc]
    """State every mixin reads; assigned by the panel's ``__init__``."""

    _account_filter: Any
    _body: ft.Container
    _budget_tabs: PulseTabs
    _categories: Any
    _dismissed_suggestions: list[dict[str, Any]]
    _envelopes: list[dict[str, Any]]
    _goal_card: Any
    _goal_field: FormTextField
    _goal_result: ft.Container
    _goal_suggestion: dict[str, Any] | None
    _goals: list[dict[str, Any]]
    _outlook: Any
    _outlook_index: int
    _pager_slot: ft.Container
    _show_commitments: bool
    _show_dismissed: bool
    _stat_detail: StatDetailPopup
    _stat_details: Any
    _stats: ft.Container
    _subtab_index: int
    _suggestion_selection: Any
    _suggestions: Any
    _summary: dict[str, Any] | None

    if TYPE_CHECKING:  # the real definitions live on the mixins / panel

        def _commitment_section(self, *args: Any, **kwargs: Any) -> Any: ...
        def _commitments_toggle(self, *args: Any, **kwargs: Any) -> Any: ...
        def _envelopes_section(self, *args: Any, **kwargs: Any) -> Any: ...
        def _flexible_section(self, *args: Any, **kwargs: Any) -> Any: ...
        def _goals_section(self, *args: Any, **kwargs: Any) -> Any: ...
        def _commitment_sections(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _load(self, *args: Any, **kwargs: Any) -> Any: ...
        def _render(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _submit_goal(self, *args: Any, **kwargs: Any) -> Any: ...
        def _suggestions_section(self, *args: Any, **kwargs: Any) -> Any: ...
        def _trims_section(self, *args: Any, **kwargs: Any) -> Any: ...
