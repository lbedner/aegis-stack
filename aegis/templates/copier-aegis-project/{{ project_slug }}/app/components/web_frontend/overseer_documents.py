"""Context for the Overseer Documents page's sections.

Steward's documents surface in the Overseer: everything on file narrowed
by search, kind and tag, a row opening its document in the drawer with
each page as extraction stored it; every extraction run; and the tags. Reads go through ``DocumentService`` on the request's session, as
the operator (every owner's documents). Registered only in projects with
the documents service (see ``overseer_sections``).
"""

from typing import Any

from app.core.formatting import format_bytes, format_relative_time
from app.services.documents import queries
from app.services.documents.domains.extraction.activity import (
    activity_rows,
    document_id_of,
)
from app.services.documents.models import DOCUMENT_KINDS, Document
from app.services.documents.service import DocumentService
from app.services.system.jobs import get_job_runner
from app.services.system.models import ComponentStatus

from .filters import short_date
from .overseer_nav import SectionRequest, page_url
from .rendering import drawer_state, ranked, status_cell, with_query

SECTIONS = (
    (None, {"overview": "Overview"}),
    ("Library", {"documents": "Documents", "activity": "Activity", "tags": "Tags"}),
)

PAGE = page_url("services", "documents")
PARTIALS = "/partials/overseer/documents"
KIND_OPTIONS = [{"id": kind, "name": kind} for kind in DOCUMENT_KINDS]
# ponytail: search matches in Python over one page; a search column on
# the query when the library outgrows a page.
LIST_SIZE = 200


DRAWER_PARAM = "document"


def document_url(document_id: int, **filters: str | None) -> str:
    """The list with this document open in the drawer, filters kept."""
    return with_query(
        f"{PAGE}/documents", **filters, **{DRAWER_PARAM: str(document_id)}
    )


def drawer_url(document_id: int) -> str:
    return f"{PARTIALS}/{document_id}/drawer"


def page_url_for(document_id: int, number: int) -> str:
    """One page's preview (the modal); ``/image`` on the end is its render."""
    return f"{PARTIALS}/{document_id}/pages/{number}"


def _matches(document: Document, q: str) -> bool:
    said = q.casefold()
    return said in (document.title or "").casefold()


def _row(
    document: Document, tags: list[str], filters: dict[str, str | None]
) -> dict[str, Any]:
    return {
        "title": {
            "label": document.title,
            "url": document_url(document.id or 0, **filters),
        },
        "kind": document.kind,
        "dated": short_date(
            document.document_date or document.received_at or document.created_at
        ),
        "pages": document.page_count,
        "size": format_bytes(document.byte_size),
        "tags": ", ".join(tags) or None,
    }


async def _overview(service: DocumentService) -> dict[str, Any]:
    summary = await service.summary()
    by_kind = summary.get("by_kind", {})
    return {
        "figures": [
            {"label": "Documents", "value": summary.get("total", 0)},
            {"label": "This month", "value": summary.get("this_month", 0)},
            {"label": "Stored", "value": format_bytes(summary.get("bytes", 0))},
            {"label": "Kinds", "value": len(by_kind)},
        ],
        "kinds": ranked(
            [
                {"label": kind, "value": f"{n:,}", "n": n}
                for kind, n in sorted(by_kind.items(), key=lambda kv: -kv[1])
            ],
            by="n",
        ),
        "tags": (await service.tag_counts())[:10],
    }


async def _documents(
    service: DocumentService, query: dict[str, str], path: str
) -> dict[str, Any]:
    kind = query.get("kind") if query.get("kind") in DOCUMENT_KINDS else None
    tag, q = query.get("tag") or None, query.get("q") or ""
    documents, _ = await service.list_documents(kind=kind, tag=tag, page_size=LIST_SIZE)
    if q:
        documents = [d for d in documents if _matches(d, q)]
    tags = await service.tags_for_many([d.id for d in documents if d.id is not None])
    filters = {"q": q, "kind": kind, "tag": tag}
    raw = query.get(DRAWER_PARAM) or ""
    shown = await service.get(int(raw)) if raw.isdigit() else None
    return drawer_state(
        DRAWER_PARAM, drawer_url(shown.id) if shown and shown.id else None
    ) | {
        "rows": [_row(d, tags.get(d.id or 0, []), filters) for d in documents],
        "kind": kind,
        "tag": tag,
        "q": q,
        "path": path,
        "upload_url": f"{PARTIALS}/upload",
    }


async def document_context(
    service: DocumentService, document_id: int
) -> dict[str, Any] | None:
    """The drawer's context for one document, or None when it is gone."""
    document = await service.get(document_id)
    if document is None or document.id is None:
        return None
    pages = await queries.pages_for(service.db, document.id)
    base = f"{PARTIALS}/{document.id}"
    return {
        "document": document,
        "details": [
            ("Kind", document.kind),
            ("Type", document.media_type),
            ("Size", format_bytes(document.byte_size)),
            ("Pages", document.page_count),
            (
                "Dated",
                short_date(document.document_date) if document.document_date else None,
            ),
            ("Received", format_relative_time(document.created_at)),
            ("Source", document.source),
            ("Protected", "Yes" if document.protected else None),
        ],
        "tags": await service.tags_for(document.id),
        "pages": [
            {
                "number": p.page_number,
                "status": p.status,
                "preview": page_url_for(document.id, p.page_number),
                "image": page_url_for(document.id, p.page_number) + "/image"
                if p.image_key
                else None,
            }
            for p in pages
        ],
        "kind_options": KIND_OPTIONS,
        "urls": {
            "save": base,
            "tags": f"{base}/tags",
            "read": f"{base}/read",
            "download": f"{base}/download",
            "delete": f"{base}/confirm-delete",
        },
    }


async def _activity(service: DocumentService) -> dict[str, Any]:
    """Every extraction run the job runner knows, newest first."""
    jobs = [j.as_dict() for j in await get_job_runner().list_all()]
    ids = {i for j in jobs if (i := document_id_of(j)) is not None}
    titles = await service.titles(ids)
    return {
        "rows": [
            {
                "title": {
                    "label": row.title,
                    "url": document_url(row.document_id),
                },
                "status": status_cell(
                    row.detail,
                    "error"
                    if row.failed
                    else "warn"
                    if row.running or row.incomplete
                    else "ok",
                ),
                "when": row.when,
            }
            for row in activity_rows(jobs, titles)
        ]
    }


async def section_context(
    section: str, documents: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    service = DocumentService(req.db)
    context: dict[str, Any] = {
        "partials": PARTIALS,
        "list_url": f"{PAGE}/documents",
        "kind_options": KIND_OPTIONS,
    }
    if section == "overview":
        return context | await _overview(service)
    if section == "documents":
        return context | await _documents(service, dict(req.query), req.path)
    if section == "activity":
        return context | await _activity(service)
    return context | {"tags": await service.tag_counts()}
