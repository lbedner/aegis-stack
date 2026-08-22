"""Planning domain: forward-looking money.

Budgets, goals, envelopes, recurring streams, and insights - what the
ledger's past implies about the future. Each module is function-style
(``async def foo(db, ...)``); the ``FinanceService`` facade in the parent
package delegates here.
"""

from app.services.finance.domains.planning import (
    allocation,
    budgets,
    envelopes,
    goals,
    insights,
    queries,
    recurring,
)

__all__ = [
    "allocation",
    "budgets",
    "envelopes",
    "goals",
    "insights",
    "queries",
    "recurring",
]
