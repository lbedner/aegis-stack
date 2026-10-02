"""Facade methods for the propose/approve queue."""

from __future__ import annotations

from typing import Any

from app.services import change_queue
from app.services.change_queue import ChangeDisplayRow, PendingChange
from app.services.finance.service.base import FinanceServiceBase


class ChangesMixin(FinanceServiceBase):
    async def propose_change(
        self,
        change_type: str,
        payload: dict[str, Any],
        *,
        owner_user_id: int | None = None,
        proposed_by_agent: str | None = None,
        conversation_id: str | None = None,
    ) -> PendingChange:
        return await change_queue.propose(
            self.db,
            change_type,
            payload,
            owner_user_id=owner_user_id,
            proposed_by_agent=proposed_by_agent,
            conversation_id=conversation_id,
        )

    async def approve_change(
        self, change_id: int, *, owner_user_id: int | None = None
    ) -> PendingChange:
        return await change_queue.approve(self.db, change_id, owner_user_id=owner_user_id)

    async def reject_change(
        self,
        change_id: int,
        *,
        owner_user_id: int | None = None,
        note: str | None = None,
    ) -> PendingChange:
        return await change_queue.reject(
            self.db, change_id, owner_user_id=owner_user_id, note=note
        )

    async def list_pending_changes(
        self, *, owner_user_id: int | None = None, status: str | None = "pending"
    ) -> list[PendingChange]:
        return await change_queue.list_changes(
            self.db, owner_user_id=owner_user_id, status=status
        )

    async def get_pending_change(
        self, change_id: int, *, owner_user_id: int | None = None
    ) -> PendingChange | None:
        return await change_queue.get_change(self.db, change_id, owner_user_id=owner_user_id)

    async def describe_pending_change(
        self, row: PendingChange
    ) -> list[ChangeDisplayRow]:
        return await change_queue.describe_change(self.db, row)

    async def propose_many_changes(
        self,
        change_type: str,
        payloads: list[dict[str, Any]],
        *,
        owner_user_id: int | None = None,
        proposed_by_agent: str | None = None,
        conversation_id: str | None = None,
    ) -> list[PendingChange]:
        return await change_queue.propose_many(
            self.db,
            change_type,
            payloads,
            owner_user_id=owner_user_id,
            proposed_by_agent=proposed_by_agent,
            conversation_id=conversation_id,
        )

    async def approve_batch(
        self,
        batch_id: str,
        *,
        owner_user_id: int | None = None,
        exclude_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        return await change_queue.approve_batch(
            self.db,
            batch_id,
            owner_user_id=owner_user_id,
            exclude_ids=exclude_ids,
        )

    async def reject_batch(
        self, batch_id: str, *, owner_user_id: int | None = None
    ) -> dict[str, Any]:
        return await change_queue.reject_batch(self.db, batch_id, owner_user_id=owner_user_id)
