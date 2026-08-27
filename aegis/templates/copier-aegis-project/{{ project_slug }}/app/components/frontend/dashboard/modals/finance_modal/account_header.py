"""The header above an account's register: identity, balance, Manage menu.

Split out of ``sidebar`` because the menu is where account-type-specific
actions land (property details today, more later) and the sidebar is
already the fattest module in this package.
"""

from __future__ import annotations

from typing import Any

import flet as ft

from app.components.frontend.controls import H3Text, NumericText, SecondaryText, Tag
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    _account_display_balance,
    _type_label,
    _usd,
)
from app.components.frontend.dashboard.modals.modal_sections import (
    headline_stat_color,
)
from app.components.frontend.theme import AegisTheme as Theme

PROPERTY_ACCOUNT_TYPE = "property"


def manage_menu_labels(account: dict[str, Any]) -> list[str]:
    """The Manage menu's items for one account, in order (pure).

    Rename and Reconcile always; Remove only for manual accounts (a
    provider account belongs to its bank connection); Property details
    only where there is a property to describe.
    """
    labels = ["Rename", "Reconcile"]
    if account.get("account_type") == PROPERTY_ACCOUNT_TYPE:
        labels.extend(("Property details", "Valuation history"))
    if account.get("classification") == "liability":
        # FW-04: the lien link only means something on a debt.
        labels.append("Secured by")
    if account.get("is_manual", False):
        labels.append("Remove")
    return labels


def _account_detail_header(
    account: dict,
    *,
    on_rename,
    on_remove,
    on_reconcile,
    on_property,
    on_valuations,
    on_secured,
) -> ft.Control:
    """The header shown above an account's register: name, type, balance, and a
    Manage menu (Rename and Reconcile always; Remove for manual accounts only —
    provider accounts are owned by the bank connection)."""
    balance = _account_display_balance(account)
    is_manual = account.get("is_manual", False)
    classification = (account.get("classification") or "asset").title()
    source = "Manual" if is_manual else "Connected"
    meta = f"{classification}  ·  {source}  ·  {(account.get('currency') or 'usd').upper()}"

    handlers = {
        "Rename": on_rename,
        "Reconcile": on_reconcile,
        "Property details": on_property,
        "Valuation history": on_valuations,
        "Secured by": on_secured,
        "Remove": on_remove,
    }
    menu_items = [
        ft.PopupMenuItem(
            text=label,
            on_click=lambda _e, handler=handlers[label]: handler(account),
        )
        for label in manage_menu_labels(account)
    ]
    manage = ft.PopupMenuButton(
        icon=ft.Icons.MORE_VERT,
        # Explicit: without it the icon inherits the theme primary (teal),
        # and accent means "act on me" - a quiet overflow trigger isn't that.
        # Same ink as ActionMenu's kebab and every other muted icon button.
        icon_color=ft.Colors.ON_SURFACE_VARIANT,
        tooltip="Manage account",
        items=menu_items,
    )

    left = ft.Column(
        [
            ft.Row(
                [
                    H3Text(
                        account.get("name", ""),
                        color=Theme.Colors.TEXT_PRIMARY,
                    ),
                    Tag(
                        text=_type_label(account.get("account_type")),
                        color=Theme.Colors.INFO,
                    ),
                ],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            SecondaryText(
                meta,
                size=Theme.Typography.CAPTION,
                color=Theme.Colors.TEXT_SECONDARY,
            ),
        ],
        spacing=Theme.Spacing.XS,
        expand=True,
    )
    right = NumericText(
        _usd(balance),
        size=Theme.Typography.H2,
        color=headline_stat_color(balance),
        weight=ft.FontWeight.W_700,
    )
    return ft.Container(
        content=ft.Row(
            [left, right, manage],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.padding.only(bottom=Theme.Spacing.SM),
    )


def panel_detail_header(panel: Any, account: dict) -> ft.Control:
    """The detail header wired to one panel's Manage handlers.

    The callsite used to be seven kwargs of plumbing in ``panel.py``;
    the wiring lives here beside the menu it feeds, so adding a menu
    item is a one-file change.
    """
    return _account_detail_header(
        account,
        on_rename=panel._open_rename,
        on_remove=panel._open_remove,
        on_reconcile=panel._open_reconcile,
        on_property=panel._open_property_details,
        on_valuations=panel._open_valuation_history,
        on_secured=panel._open_secured_by,
    )
