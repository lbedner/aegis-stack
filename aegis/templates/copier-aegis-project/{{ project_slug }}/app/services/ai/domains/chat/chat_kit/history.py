"""Durable conversation persistence for chat surfaces.

GENERIC. Persists chat turns to the template's ``conversation`` /
``conversation_message`` tables so a page refresh resumes the thread instead
of losing it. One rolling conversation per (surface, subject, user) — a
deterministic id makes find-or-create a primary-key lookup, no JSON querying,
and cleanly separates one project's thread from another's.

This is durability, not unbounded context: only the recent TAIL is loaded for
display, and the caller still clips what the model reads. Old turns stay in
the table but scroll out of the model's window.

Commit policy: this store ADDS + FLUSHES but never commits. The request's
session dependency (``get_async_db``) commits once the streamed response
finishes; leaving the commit to the caller also keeps transactional test
fixtures isolated (a mid-fixture commit would fight their rollback).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.conversation import Conversation, ConversationMessage

from .models import ChatMessage


class ConversationStore:
    """One durable thread per (surface, subject, user)."""

    def __init__(self, surface: str) -> None:
        self.surface = surface

    def _conversation_id(self, user_id: str, subject_id: Any) -> str:
        # Deterministic, so find-or-create is a PK get. subject_id is the
        # caller's opaque scope key (a project id for the metrics surface).
        return f"{self.surface}:{subject_id}:{user_id}"

    async def load_tail(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        subject_id: Any,
        limit: int,
    ) -> list[ChatMessage]:
        """The most recent ``limit`` turns, oldest-first, ready for display."""
        cid = self._conversation_id(user_id, subject_id)
        rows = (
            await session.exec(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == cid)
                .order_by(col(ConversationMessage.timestamp).desc())
                .limit(limit)
            )
        ).all()
        out: list[ChatMessage] = []
        for row in reversed(rows):  # desc + reverse = oldest-first
            if row.role in ("user", "assistant") and row.content:
                # Columns are naive UTC; mark the ISO string as UTC ("Z") so
                # the browser renders it in the viewer's local time.
                out.append(
                    ChatMessage(
                        role=row.role,  # type: ignore[arg-type]
                        content=row.content,
                        timestamp=row.timestamp.isoformat() + "Z",
                    )
                )
        return out

    async def append_turn(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        subject_id: Any,
        user_text: str,
        assistant_text: str,
    ) -> None:
        """Save one completed exchange (user question + assistant answer).

        Timestamps are strictly increasing WITHIN a conversation: the base is
        ``max(now, latest stored message + 1ms)``, so two turns fired in the
        same wall-clock millisecond still order deterministically (a plain
        ``now`` + fixed offset interleaves — the intra-turn offset can exceed
        the inter-turn gap). The conversation is created before its messages so
        the message->conversation FK holds on Postgres and in the SQLite test
        DB (the template's conftest enables ``PRAGMA foreign_keys=ON``).
        """
        cid = self._conversation_id(user_id, subject_id)
        now = datetime.now(UTC).replace(tzinfo=None)  # column is naive

        conv = await session.get(Conversation, cid)
        if conv is None:
            # created_at/updated_at are passed explicitly and naive: the model
            # defaults them to an AWARE datetime.now(UTC), which asyncpg
            # rejects against these "timestamp without time zone" columns.
            conv = Conversation(
                id=cid,
                user_id=user_id,
                meta_data={"surface": self.surface, "subject_id": subject_id},
                created_at=now,
                updated_at=now,
            )
            session.add(conv)
            await session.flush()  # create before the FK'd messages
        conv.updated_at = now
        session.add(conv)

        latest = (
            await session.exec(
                select(func.max(ConversationMessage.timestamp)).where(
                    ConversationMessage.conversation_id == cid
                )
            )
        ).one()
        base = now if latest is None else max(now, latest + timedelta(milliseconds=1))

        session.add(
            ConversationMessage(
                conversation_id=cid, role="user", content=user_text, timestamp=base
            )
        )
        session.add(
            ConversationMessage(
                conversation_id=cid,
                role="assistant",
                content=assistant_text,
                timestamp=base + timedelta(milliseconds=1),
            )
        )
        await session.flush()  # caller (get_async_db) owns the commit
