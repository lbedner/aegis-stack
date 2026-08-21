"""Shared lifecycle for the finance dialog's data panels.

Every panel used to hand-roll the same trio - fetch on mount, reload
when the shared account filter changes, reload when its tab is revisited
- and every copy drifted: Budget shipped without the filter leg,
Projection shipped without the revisit leg (a freshly confirmed payment
stayed invisible on the Projected page until the dialog reopened,
confirmed live). The base owns all three; a subclass implements
``_load`` and cannot forget a leg it never writes.

Its own module rather than ``finance_modal``: the attention tab is
imported BY ``finance_modal``, so a base living there could never be
inherited from that side of the cycle. This module imports nothing from
its consumers at module scope, which is what makes it inheritable by
all of them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import flet as ft

if TYPE_CHECKING:
    from .finance_modal import AccountFilter


class FinancePanel(ft.Container):
    """See the module docstring. Panels with genuinely different behavior
    override the leg they mean to change (Bills & Income refilters its
    last fetch locally instead of refetching; Uncategorized debounces and
    keeps its staging state) - an override is a visible decision, where a
    fresh copy was a silent drift risk.
    """

    def __init__(
        self,
        page: ft.Page,
        account_filter: AccountFilter | None = None,
        register_filter_listener: Callable[[Callable[[], None]], None] | None = None,
        **container_kwargs: Any,
    ) -> None:
        super().__init__(**container_kwargs)
        self.page = page
        if account_filter is None:
            # Deferred: finance_modal imports this module at its top, so
            # the reverse import has to wait until call time.
            from .finance_modal import AccountFilter

            account_filter = AccountFilter()
        self._account_filter = account_filter
        if register_filter_listener is not None:
            register_filter_listener(self._on_account_filter_change)

    async def _load(self) -> None:
        raise NotImplementedError

    def _reload(self) -> None:
        if self.page:
            self.page.run_task(self._load)

    def did_mount(self) -> None:
        self._reload()

    def _on_account_filter_change(self) -> None:
        self._reload()

    def refresh_on_revisit(self) -> None:
        self._reload()
