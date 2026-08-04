"""Setup surfaces, behind the gear: connections, categories, payees.

None is a daily read. You open Connections when wiring a provider up or
when one breaks, Categories when you are curious about the taxonomy or
pruning it, and Payees when a logo is wrong or a payee needs correcting.
Sitting in the main tab row they competed for attention with the screens
you actually check, so they moved behind an icon - which is the one place
nesting is honest, because "configuration" is a real category and these
are its members.
"""

import flet as ft

from app.components.frontend.controls.tabs import PulseTabs


class SettingsTab(ft.Container):
    """Connections, Categories and Payees, lazily built on first visit."""

    def __init__(
        self,
        page: ft.Page,
        account_filter=None,
        register_filter_listener=None,
    ) -> None:
        super().__init__()
        self.page = page
        self.expand = True
        self._index = 0

        # Deferred: ``finance_modal`` imports this module, so importing it
        # at module scope would be a cycle.
        from .finance_categories_tab import CategoriesTab
        from .finance_modal import ConnectionsTab
        from .finance_payees_tab import PayeesTab

        factories = [
            ("Connections", lambda: ConnectionsTab(page)),
            ("Categories", lambda: CategoriesTab(page)),
            (
                "Payees",
                lambda: PayeesTab(page, account_filter, register_filter_listener),
            ),
        ]
        holders = [ft.Container(expand=True) for _ in factories]
        holders[0].content = factories[0][1]()

        def _on_change(event: ft.ControlEvent) -> None:
            index = int(event.control.selected_index or 0)
            self._index = index
            holder = holders[index]
            if holder.content is None:
                holder.content = factories[index][1]()
                if holder.page is not None:
                    holder.update()

        self.content = PulseTabs(
            selected_index=0,
            tabs=[
                ft.Tab(text=label, content=holder)
                for (label, _), holder in zip(factories, holders)
            ],
            expand=True,
            on_change=_on_change,
        )
