"""FastAPI dependency providers for the document service.

Mirrors ``finance/deps.py``. Owner scoping is ``get_owner_user_id`` in
``app.services.shared.deps``. Documents dedupe PER OWNER, so getting it
wrong would make one person's scan collide with another's.
"""

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_async_db
from app.services.documents.service import DocumentService


async def get_document_service(
    db: AsyncSession = Depends(get_async_db),
) -> DocumentService:
    """Provide a DocumentService.

    ``get_async_db`` is the FastAPI-dependency form of the session, and
    what every other service injects; ``get_async_session`` is the same
    transaction handling wrapped as a context manager, for scripts and
    background jobs that own their own scope. Both commit on success.
    """
    return DocumentService(db)
