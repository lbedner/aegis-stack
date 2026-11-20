"""Context for the Overseer Documents page's sections.

Steward's documents surface in the Overseer: everything on file narrowed
by search, kind and tag, a row opening its document in the drawer with
each page as extraction stored it; every extraction run; the tags; and
the mail that came in, with what each message became. Reads go through ``DocumentService`` on the request's session, as
the operator (every owner's documents). Registered only in projects with
the documents service (see ``overseer_sections``).
"""

from collections.abc import AsyncIterator
from typing import Any

from app.core.formatting import counted, format_bytes, format_relative_time
from app.services.documents.service import (
    DOCUMENT_KINDS,
    Document,
    DocumentService,
    activity_rows,
    document_id_of,
    pages_for,
)
from app.services.mail.arrivals import Arrival, arrivals
from app.services.mail.pull import mailbox_status
from app.services.system.jobs import get_job_runner
from app.services.system.models import ComponentStatus

from .filters import short_date
from .overseer_live import job_frames, job_state
from .overseer_nav import SectionRequest, page_url
from .rendering import drawer_state, hx_replace, ranked, status_cell, with_query

SECTIONS = (
    (None, {"overview": "Overview"}),
    (
        "Library",
        {
            "documents": "Documents",
            "activity": "Activity",
            "tags": "Tags",
            "mail": "Mail",
        },
    ),
)

PAGE = page_url("services", "documents")
PARTIALS = "/partials/overseer/documents"
KIND_OPTIONS = [{"id": kind, "name": kind} for kind in DOCUMENT_KINDS]
# ponytail: search matches in Python over one page; a search column on
# the query when the library outgrows a page.
LIST_SIZE = 200


DRAWER_PARAM = "document"
# The mail import the list follows, by job id (``mail_job_view``).
MAIL_JOB_PARAM = "mail_job"


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


def mail_job_url(job_id: str) -> str:
    """The list, following a mail import as it runs."""
    return with_query(f"{PAGE}/documents", **{MAIL_JOB_PARAM: job_id})


def mail_job_view(job: dict[str, Any]) -> dict[str, Any]:
    """A mail import as the list shows it (``job_state``): ended, how many
    messages it filed and what they carried."""

    def ended(done: dict[str, Any]) -> dict[str, Any]:
        said = (
            f"{counted(done.get('messages_new', 0), 'message')} filed "
            f"({done.get('messages_duplicate', 0):,} already on file): "
            f"{counted(done.get('letters_filed', 0), 'letter')}, "
            f"{counted(done.get('attachments_filed', 0), 'attachment')}."
        )
        return {"label": said, "tone": "muted"}

    events = f"{PARTIALS}/mail/jobs/{job['job_id']}/events"
    return job_state(job, events, "Importing mail", ended)


def mail_job_events(job_id: str) -> AsyncIterator[str]:
    """A mail import over SSE (``job_frames``), the last state loading the
    list again so the documents it filed show."""
    reload = hx_replace(f"{PAGE}/documents", "#documents-list")
    return job_frames(job_id, mail_job_view, reload)


async def _overview(service: DocumentService) -> dict[str, Any]:
    summary = await service.summary()
    by_kind = summary.by_kind
    return {
        "figures": [
            {"label": "Documents", "value": summary.total},
            {"label": "This month", "value": summary.this_month},
            {"label": "Stored", "value": format_bytes(summary.bytes)},
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
    # The search (``q``) narrows the rows on the page as you type
    # (``filter_input``); it only rides along in the URL.
    documents, _ = await service.list_documents(kind=kind, tag=tag, page_size=LIST_SIZE)
    tags = await service.tags_for_many([d.id for d in documents if d.id is not None])
    filters = {"q": q, "kind": kind, "tag": tag}
    raw = query.get(DRAWER_PARAM) or ""
    shown = await service.get(int(raw)) if raw.isdigit() else None
    followed = query.get(MAIL_JOB_PARAM)
    mail_job = await get_job_runner().lookup(followed) if followed else None
    return drawer_state(
        DRAWER_PARAM, drawer_url(shown.id) if shown and shown.id else None
    ) | {
        "rows": [_row(d, tags.get(d.id or 0, []), filters) for d in documents],
        "kind": kind,
        "tag": tag,
        "q": q,
        "path": path,
        "upload_url": f"{PARTIALS}/upload",
        "mail_job": mail_job_view(mail_job.as_dict()) if mail_job else None,
    }


async def document_context(
    service: DocumentService, document_id: int
) -> dict[str, Any] | None:
    """The drawer's context for one document, or None when it is gone."""
    document = await service.get(document_id)
    if document is None or document.id is None:
        return None
    pages = await pages_for(service.db, document.id)
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


def _arrival_row(arrival: Arrival) -> dict[str, Any]:
    """One message as the Mail table draws it: its subject opens the
    letter it became, each attachment its document."""
    letter = arrival.letter_id
    return {
        "sender": arrival.sender,
        "subject": {
            "label": arrival.subject,
            "url": document_url(letter) if letter else None,
        },
        "attachments": [
            {"label": a.filename, "url": document_url(a.document_id)}
            for a in arrival.attachments
        ]
        or None,
        "became": arrival.became,
        "via": arrival.via,
    }


async def _mail(service: DocumentService) -> dict[str, Any]:
    """The mailbox the app pulls and how its last pull went, then what came
    in by day: the rows the ``arrivals`` tool reads."""
    mailbox = await mailbox_status(service.db)
    pulled = None
    if mailbox is not None:
        pulled = mailbox.error or (
            f"last pulled {format_relative_time(mailbox.pulled_at)}"
            if mailbox.pulled_at
            else "nothing pulled yet"
        )
    return {
        "mailbox": mailbox,
        "pulled": pulled,
        "days": [
            {"date": day.date, "rows": [_arrival_row(m) for m in day.messages]}
            for day in await arrivals(service.db, owner_user_id=None)
        ],
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
    if section == "mail":
        return context | await _mail(service)
    return context | {"tags": await service.tag_counts()}
