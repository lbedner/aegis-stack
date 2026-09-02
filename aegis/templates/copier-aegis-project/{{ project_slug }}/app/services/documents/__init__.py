"""Document store: keep the paper, deduped and findable."""

from app.services.documents.models import (
    DOCUMENT_KINDS,
    Document,
    DocumentPage,
    DocumentTag,
)
from app.services.documents.service import DocumentService

__all__ = [
    "DOCUMENT_KINDS",
    "Document",
    "DocumentPage",
    "DocumentTag",
    "DocumentService",
]
