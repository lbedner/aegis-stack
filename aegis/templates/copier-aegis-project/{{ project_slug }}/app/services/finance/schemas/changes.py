"""Pending-change shapes: the confirmation card's data contract.

A topic module of the ``schemas`` package; every name here is
re-exported from its root. The card renders THIS response - which is
built from the stored queue row, which is what approval executes - so
what the user sees and what runs are the same thing by construction.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.services.finance.models import FinancePendingChange


class ChangeProposal(BaseModel):
    """POST body for /finance/changes: one proposed mutation."""

    change_type: str
    payload: dict[str, Any]
    proposed_by_agent: str | None = None
    conversation_id: str | None = None


class ChangeDisplayRow(BaseModel):
    """One label/value line of the card body - resolved from the
    database at read time, never authored by a model."""

    label: str
    value: str


class PendingChangeResponse(BaseModel):
    id: int
    change_type: str
    title: str
    status: str
    display: list[ChangeDisplayRow]
    proposed_by_agent: str | None
    conversation_id: str | None
    batch_id: str | None
    error: str | None
    note: str | None = None
    created_at: datetime
    resolved_at: datetime | None

    @classmethod
    def from_row(
        cls,
        row: FinancePendingChange,
        *,
        title: str,
        display: list[ChangeDisplayRow],
    ) -> PendingChangeResponse:
        if row.id is None:
            raise ValueError("pending change row has no id - flush before responding")
        return cls(
            id=row.id,
            change_type=row.change_type,
            title=title,
            status=row.status,
            display=display,
            proposed_by_agent=row.proposed_by_agent,
            conversation_id=row.conversation_id,
            batch_id=row.batch_id,
            error=(row.result or {}).get("error"),
            note=(row.result or {}).get("note"),
            created_at=row.created_at,
            resolved_at=row.resolved_at,
        )


class PendingChangeListResponse(BaseModel):
    items: list[PendingChangeResponse]
    total: int


class BatchResolveRequest(BaseModel):
    """POST body for batch approval: the vetoed row ids (rejected, not
    deferred - a veto is a decision)."""

    exclude_ids: list[int] = []


class BatchResolveResponse(BaseModel):
    approved: int
    rejected: int
    failed: int
