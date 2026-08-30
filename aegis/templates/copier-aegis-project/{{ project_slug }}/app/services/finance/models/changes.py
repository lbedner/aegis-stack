"""The propose/approve queue: AI writes as pending changes (FW-05).

Confirmation is structural: the sandbox's only write tool is ``propose``,
and execution happens exclusively when the app user approves - no
direct-write tool exists, so the model cannot skip it. Every resolution
keeps its row: the queue IS the audit trail.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Column, Index
from sqlmodel import Field, SQLModel

from app.services.finance.models.base import _SCHEMA, _utcnow

PENDING_CHANGE_STATUSES = ("pending", "approved", "rejected", "expired")


class FinancePendingChange(SQLModel, table=True):
    """One proposed mutation, from proposal through resolution.

    ``payload`` is the exact mutation the executor will run on approval -
    the confirmation card renders THIS row, so what the user sees is what
    executes, by construction. ``result`` records the execution outcome
    (or refusal reason) for the audit trail.
    """

    __tablename__ = "finance_pending_change"
    __table_args__ = (
        Index("ix_finance_pending_owner", "owner_user_id"),
        Index("ix_finance_pending_status", "status"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired')",
            name="ck_finance_pending_status",
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(default=None)
    change_type: str = Field(max_length=64)
    payload: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("payload", JSON, nullable=False)
    )
    # Who asked: agent slug + the conversation the proposal was made in,
    # so the card can live inline and the audit names its author.
    proposed_by_agent: str | None = Field(default=None, max_length=64)
    conversation_id: str | None = Field(default=None, max_length=64)
    # Rows proposed together share a batch id ("approve them all" is
    # one decision over many auditable rows); NULL = a lone proposal.
    batch_id: str | None = Field(default=None, max_length=36, index=True)
    status: str = Field(default="pending", max_length=16)
    result: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("result", JSON, nullable=False)
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    resolved_at: datetime | None = Field(default=None)
