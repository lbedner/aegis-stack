"""
Finance Service Detail Modal

A Quicken-style finance workspace, organised into tabs:

* **Accounts** — the register. A left sidebar lists accounts grouped into
  Banking / Credit / Investments / etc., each with its balance and a grand
  total; selecting one shows an account-detail header (with a Manage menu)
  above its transactions (or holdings, for investment accounts). The sidebar
  only lives on this tab.
* **Overview** — a net-worth summary (assets, liabilities, net worth) with a
  per-group breakdown. No sidebar; this is the "home" landing.

Data is fetched async through the internal ``APIClient`` (never a DB session
from the frontend). All colours, spacing, and type come from ``AegisTheme``.
"""

from collections.abc import Callable
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    BodyText,
    SecondaryText,
)
from app.components.frontend.controls.dropdown import Dropdown
from app.components.frontend.dashboard.modals.finance_modal.constants import (
    _ACCOUNT_GROUPS,
)

# Named rows in the import review's detail sections before the tail folds
# into a count. A Quicken tree can carry hundreds of new categories, and a
# dialog that scrolls for a page stops being read at all.
# One height for every Overview card, so the row has a single baseline.
# Named slices in the spending donut (and rows in the list under it) before
# the tail folds into "Other". Five left "Other" as the biggest slice on any
# real ledger, which hides exactly the breakdown the card exists to show.
# Measured against a real ledger (23 parent-level categories after the
# spending_by_category rollup): 10 slices still left "Other" at 16.3%; 15
# gets it to 5.3%, with everything past #15 individually under 1% of total
# spend - the tail at that point really is "everything else", not a few
# disguised top categories. PieChartCard's legend scrolls within its fixed
# height (modal_sections.py) rather than clipping, so this isn't bounded
# by legend space anymore.
from app.components.frontend.dashboard.modals.finance_modal.formatting import _group_for
from app.components.frontend.theme import AegisTheme as Theme


class AccountFilter:
    """Which accounts the dashboard is currently looking at.

    ``selected`` is None for "all accounts" - the default. An EMPTY set is a
    legal staging state ("Remove all", then check the two you want) and the
    page renders empty rather than quietly falling back to everything.
    Owned by the finance dialog and shared with its tabs, so a narrower view
    can follow the user across tabs as more of them opt in.
    """

    def __init__(self) -> None:
        self.selected: set[int] | None = None

    @property
    def is_empty(self) -> bool:
        """Nothing checked - distinct from None, which means everything."""
        return self.selected is not None and not self.selected

    def allows(self, account_id: Any) -> bool:
        """Does this row survive the filter?

        A row with NO account always does. A bill or income typed in by
        hand has ``account_id = None``, and asking "is None among the
        chosen accounts" is always False - so any narrowing made every
        hand-entered row vanish from every tab at once. It belongs to no
        account, so no account selection is a statement about it.
        """
        if account_id is None:
            return True
        return self.selected is None or account_id in self.selected

    def params(self) -> dict[str, Any]:
        """Query params for endpoints that accept ``account_ids``.

        Never called for the empty state: an empty list would drop out of
        the query string and read as "no filter" server-side - the exact
        opposite of what an empty selection means. Callers check
        ``is_empty`` and skip the fetch instead.
        """
        if self.selected is None:
            return {}
        return {"account_ids": sorted(self.selected)}

    def toggle(self, account_id: int, all_ids: list[int]) -> None:
        current = set(self.selected) if self.selected is not None else set(all_ids)
        if account_id in current:
            current.discard(account_id)
        else:
            current.add(account_id)
        # Everything selected means the filter is off; empty stays empty.
        self.selected = None if current >= set(all_ids) else current


class AccountFilterButton(Dropdown):
    """Multi-select account-scope filter: a ``Dropdown`` trigger reading
    "All accounts" / "N of M accounts", opening a checkable-dot panel
    grouped the same way the Accounts sidebar is (``_ACCOUNT_GROUPS``).

    Extracted from ``OverviewTab`` (its original, only home) so
    ``UncategorizedPanel`` can offer the exact same filter instead of
    inventing a second account picker. Owns its own ``AccountFilter``
    state unless one is passed in - pass the dialog-level shared
    instance (``FinanceDetailDialog._account_filter``) so a narrower
    view keeps following the user from Overview into Review too.
    ``set_accounts`` rebuilds the menu from a freshly fetched account
    list; the caller's ``on_change`` fires after every toggle so it can
    reload its own data - this control has no idea what that data is.
    """

    def __init__(
        self,
        *,
        on_change: Callable[[], None],
        account_filter: AccountFilter | None = None,
    ) -> None:
        self.filter = account_filter or AccountFilter()
        self._on_change = on_change
        super().__init__(
            trigger=ft.Row(
                [
                    ft.Icon(
                        ft.Icons.FILTER_ALT_OUTLINED,
                        size=16,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    SecondaryText("All accounts", size=Theme.Typography.BODY_SMALL),
                ],
                spacing=4,
                tight=True,
            ),
        )

    def set_accounts(self, accounts: list[dict]) -> None:
        """Check marks show what is in view: with no filter every account
        is checked, because that is what "All accounts" means. Toggling
        the last account off (or every account on) collapses back to
        All - a zero-account dashboard is a dead end nobody asks for."""
        all_ids = [a.get("id") for a in accounts if a.get("id") is not None]
        active = self.filter.selected is not None

        def show_all(_e: ft.ControlEvent) -> None:
            self.filter.selected = None
            self._on_change()

        def remove_all(_e: ft.ControlEvent) -> None:
            self.filter.selected = set()
            self._on_change()

        def toggler(account_id: int):
            def _toggle(_e: ft.ControlEvent) -> None:
                self.filter.toggle(account_id, all_ids)
                self._on_change()

            return _toggle

        def dot(selected: bool) -> ft.Container:
            # The same dot language the chart legends use: teal fill when
            # the account is in view, a hollow outline when it is not.
            return ft.Container(
                width=10,
                height=10,
                border_radius=5,
                bgcolor=Theme.Colors.ACCENT if selected else None,
                border=None if selected else ft.border.all(1.5, ft.Colors.OUTLINE),
            )

        def entry(leading: ft.Control, label: str, on_click: Callable) -> ft.Container:
            # ``ink=True`` gives the Material press ripple that stock
            # PopupMenuItem got for free; here it's a plain row inside the
            # Dropdown's own panel, so it has to be asked for explicitly.
            # Deliberately doesn't close the dropdown - picking accounts is
            # a multi-select, so each click should just update that row's
            # dot and leave the panel open for the next one. It closes via
            # its own trigger or an outside click instead.
            return ft.Container(
                content=ft.Row(
                    [leading, BodyText(label, color=ft.Colors.ON_SURFACE)],
                    spacing=Theme.Spacing.SM,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                on_click=on_click,
                ink=True,
                border_radius=Theme.Components.BUTTON_RADIUS,
                padding=ft.padding.symmetric(
                    vertical=Theme.Spacing.SM, horizontal=Theme.Spacing.MD
                ),
            )

        def header(text: str) -> ft.Container:
            # Same caption treatment as the sidebar's group headers.
            return ft.Container(
                content=SecondaryText(
                    text,
                    size=Theme.Typography.CAPTION,
                    color=Theme.Colors.TEXT_SECONDARY,
                    weight=ft.FontWeight.W_600,
                ),
                padding=ft.padding.only(
                    left=Theme.Spacing.MD,
                    right=Theme.Spacing.MD,
                    top=Theme.Spacing.MD,
                    bottom=Theme.Spacing.XS,
                ),
            )

        rows: list[ft.Control] = [
            entry(dot(not active), "All accounts", show_all),
            entry(
                ft.Icon(
                    ft.Icons.CLEAR_ALL,
                    size=14,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                "Remove all",
                remove_all,
            ),
            ft.Divider(height=1, color=Theme.Colors.BORDER_SUBTLE),
        ]
        # Same buckets, same order as the Accounts sidebar - the picker
        # should read like a compact copy of the page it filters.
        grouped: dict[str, list[dict]] = {}
        for account in accounts:
            if account.get("id") is None:
                continue
            grouped.setdefault(_group_for(account.get("account_type", "")), []).append(
                account
            )
        for group_label, _types in _ACCOUNT_GROUPS:
            group = grouped.get(group_label)
            if not group:
                continue
            rows.append(header(group_label))
            for account in group:
                account_id = account["id"]
                rows.append(
                    entry(
                        dot(self.filter.allows(account_id)),
                        str(account.get("name", "")),
                        toggler(account_id),
                    )
                )

        selected_count = sum(1 for i in all_ids if self.filter.allows(i))
        label = (
            "All accounts"
            if not active
            else f"{selected_count} of {len(all_ids)} accounts"
        )
        self.set_panel(
            ft.Column(rows, spacing=0, scroll=ft.ScrollMode.AUTO, tight=True)
        )
        self.set_trigger(
            ft.Row(
                [
                    ft.Icon(
                        ft.Icons.FILTER_ALT if active else ft.Icons.FILTER_ALT_OUTLINED,
                        size=16,
                        color=Theme.Colors.ACCENT
                        if active
                        else ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    SecondaryText(label, size=Theme.Typography.BODY_SMALL),
                ],
                spacing=4,
                tight=True,
            )
        )
