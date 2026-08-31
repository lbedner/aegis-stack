"""Lightweight per-request catalog reads.

The full catalog service (``llm_service``) is a management surface;
this module is what a hot path asks one small question of.
"""

from __future__ import annotations

from sqlmodel import select

from app.core.db import get_async_session
from app.services.ai.models.llm import LargeLanguageModel


async def context_window_for(model_id: str) -> int | None:
    """The catalog's context window for one model id, or None when the
    model is not in the catalog (unknown local tags, fresh installs)."""
    async with get_async_session() as session:
        row = (
            await session.exec(
                select(LargeLanguageModel).where(
                    LargeLanguageModel.model_id == model_id
                )
            )
        ).first()
    return row.context_window if row else None
