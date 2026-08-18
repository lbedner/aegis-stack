"""Recurring streams: the bills and income that repeat.

Four concerns, one per module - ``streams`` for the row's lifecycle,
``matching`` for reconciling a payment against a bill, ``forecast`` for
walking a balance forward, ``queries`` for the reads only this domain
issues. The package boundary is the API: callers reach every verb as
``recurring.foo(db, ...)`` and never import a submodule.
"""

from app.services.finance.domains.planning.recurring import (
    forecast,
    matching,
    queries,
    streams,
)
from app.services.finance.domains.planning.recurring.forecast import (
    budget_drawdowns,
    goal_drawdowns,
    project_balances,
)
from app.services.finance.domains.planning.recurring.matching import (
    recurring_match_candidates,
)
from app.services.finance.domains.planning.recurring.streams import (
    _STREAM_DIRECTIONS,
    _STREAM_FREQUENCIES,
    attach_transaction_to_stream,
    confirm_recurring,
    create_recurring_stream,
    delete_recurring,
    get_recurring,
    list_recurring,
    mute_recurring,
    pause_recurring,
    payment_stream_ids,
    resume_recurring,
    stream_category_names,
    transfer_stream_ids,
    unmute_recurring,
    update_recurring,
)

__all__ = [
    "_STREAM_DIRECTIONS",
    "_STREAM_FREQUENCIES",
    "attach_transaction_to_stream",
    "budget_drawdowns",
    "confirm_recurring",
    "create_recurring_stream",
    "delete_recurring",
    "forecast",
    "get_recurring",
    "goal_drawdowns",
    "list_recurring",
    "matching",
    "mute_recurring",
    "pause_recurring",
    "payment_stream_ids",
    "project_balances",
    "queries",
    "recurring_match_candidates",
    "resume_recurring",
    "stream_category_names",
    "streams",
    "transfer_stream_ids",
    "unmute_recurring",
    "update_recurring",
]
