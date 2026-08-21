"""Process-level finance view state, keyed per owner.

The account filter caused a real scare: a projection read one way under a
narrowed filter, the Flet session restarted (page reload; every
hot-reload in dev), the filter silently reset to "All accounts", and the
same screen told a different story. The dialog is cached on ``page.data``
and ``SessionState`` lives there too, so both die with the page - neither
can carry view state across sessions.

This store is APP-scoped (a module global, no page anywhere near it - the
same rule ``app/core`` follows), so it survives page reloads for as long
as the server process runs. Deliberately in memory and nothing more:
losing view preferences on a server restart is fine, and persisting them
(client settings, a table) is a later decision this module should not
pre-empt.

Keyed per owner because an auth stack has several users on one process;
one user's narrowed view must never become another's. A standalone stack
passes a fixed key.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.components.frontend.dashboard.modals.finance_modal import AccountFilter

# The one fixed key a standalone (no-auth) stack uses.
SOLO_OWNER_KEY = "solo"


@dataclass
class FinanceViewState:
    """What the finance dialog remembers about how you were looking at it.

    Holds the SAME mutable objects the dialog uses (``AccountFilter``
    itself, not a copy of its fields) - a recreated dialog adopts the
    instance and every mutation lands here for the next one. New view
    state (a range chip, a remembered tab) is a field on this class, not
    a second store.
    """

    account_filter: AccountFilter = field(default_factory=AccountFilter)


_STATES: dict[str, FinanceViewState] = {}


def finance_view_state(*, owner_key: str) -> FinanceViewState:
    """The owner's view state, created on first use."""
    if owner_key not in _STATES:
        _STATES[owner_key] = FinanceViewState()
    return _STATES[owner_key]


def reset_finance_view_state() -> None:
    """Drop every owner's view state (tests, and nothing else)."""
    _STATES.clear()
