"""Document store: keep the paper, deduped and findable.

The spine, at this level:

- ``service`` - the facade: ingest, read, list, tag, retire
- ``models`` - document, document_tag, document_page
- ``queries`` - every read, batched
- ``health`` - what the dashboard shows
- ``deps`` - the request-scoped service

Domains:

- ``domains.extraction`` - turning a stored document into page-addressed
  text: the run, the PDF, the vision reader, where it runs, and the job
  entry points it runs through.
"""

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
