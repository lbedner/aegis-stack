"""The finance write surface for agents: the ids its proposals need.

Split from ``ai_tools`` (the read surface): ``categories``, ``bills``,
``bill_candidates`` and ``tags`` are the lookups a finance payload is
built from. Filing the proposal itself is the shared queue's job - the
``propose`` family lives in ``app.services.change_queue.tools``
and files a card for any service's change type, finance's included.
Lookups read the turn's owner, as the read surface does.
"""

from __future__ import annotations

from typing import Any

from app.core.db import get_async_session
from app.core.tools import current_owner_user_id, register_tool


async def categories() -> dict[str, Any]:
    """Every assignable category: 'id', 'name' and 'classification'
    ('expense' | 'income' | 'transfer'). The id is what a
    transaction.categorize proposal's 'category_id' takes.
    """
    from app.services.finance.domains.ledger import queries as ledger_queries

    async with get_async_session() as session:
        rows = await ledger_queries.all_categories(
            session, owner_user_id=current_owner_user_id.get(), include_archived=False
        )
    return {
        "categories": [
            {"id": row.id, "name": row.name, "classification": row.classification}
            for row in rows
        ]
    }


async def bills() -> dict[str, Any]:
    """Every live bill and income stream: 'id', 'name', 'direction'
    ('outflow' | 'inflow'), 'frequency', 'amount' (cents - ALWAYS a
    number, never null: the figure the user declared, else the one
    measured from the bill's own payments), 'amount_is_declared'
    (whether a human typed it), 'next_expected_date' and 'last_date'
    (ISO or null). The id is what a recurring.match proposal's
    'stream_id' takes.

    'amount' used to be the raw ``expected_amount``, which is null on
    most streams because only a hand-entered bill sets it - so this tool
    reported 40 of one real ledger's bills as having "no amount" while
    the measured figure sat beside it unread, and refused to project on
    that basis.
    """
    from app.services.finance.domains.planning.recurring import queries

    async with get_async_session() as session:
        rows = await queries.active_streams(session, owner_user_id=current_owner_user_id.get())
    return {
        "bills": [
            {
                "id": s.id,
                "name": s.name,
                "direction": s.direction,
                "frequency": s.frequency,
                "amount": s.amount,
                "amount_is_declared": s.expected_amount is not None,
                "next_expected_date": (
                    s.next_expected_date.isoformat() if s.next_expected_date else None
                ),
                "last_date": s.last_date.isoformat() if s.last_date else None,
            }
            for s in rows
        ]
    }


async def bill_candidates(stream_id: int) -> dict[str, Any]:
    """The ranked shortlist of unclaimed transactions that could be this
    bill's payment - the same heuristic the app's manual match picker
    uses (direction, amount band, due-date window, name affinity).
    Each candidate's 'id' is what a recurring.match proposal's
    'transaction_id' takes. Propose matches ONLY from this list."""
    from app.services.finance.domains.planning.recurring.matching import (
        recurring_match_candidates,
    )

    async with get_async_session() as session:
        rows = await recurring_match_candidates(session, stream_id, owner_user_id=current_owner_user_id.get())
    return {
        "stream_id": stream_id,
        "candidates": [
            {
                "id": t.id,
                "date": t.date_.isoformat(),
                "payee": t.merchant_name or t.name,
                "amount": t.amount,
                "account_id": t.account_id,
            }
            for t in rows
        ],
    }


async def tags() -> dict[str, Any]:
    """Every live tag with how many transactions wear it: 'id', 'name',
    'count'. Tags are the label axis ORTHOGONAL to categories (a
    "Business" tag on a Software-categorized row). A transaction.tag
    payload takes the NAME - reuse an existing spelling from here before
    coining a new one."""
    from app.services.finance.domains.ledger.transactions import list_tags

    async with get_async_session() as session:
        rows = await list_tags(session, owner_user_id=current_owner_user_id.get())
    return {"tags": [{"id": t.id, "name": t.name, "count": count} for t, count in rows]}


# Built-in registration: importing this module makes the tools grantable
# via the agent registry. replace=True keeps re-imports idempotent.
register_tool(
    "categories",
    categories,
    description="Assignable categories with the ids proposals need",
    replace=True,
    effect="read",
)
register_tool(
    "bills",
    bills,
    description="Live bills and income streams with the ids matches need",
    replace=True,
    effect="read",
)
register_tool(
    "bill_candidates",
    bill_candidates,
    description="Ranked unclaimed transactions that could be a bill's payment",
    replace=True,
    effect="read",
)
register_tool(
    "tags",
    tags,
    description="The tag directory: names, ids and usage counts",
    replace=True,
    effect="read",
)
