"""The Overseer Documents page, in Steward's shape: everything on file,
narrowed by search, kind and tag; one document in a drawer with its pages
as extraction stored them; every extraction run; and the tags. Every
change goes through ``DocumentService`` on the request's session; files
land in the object store.
"""

from collections.abc import Generator
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

pytest.importorskip(
    "app.services.documents", reason="no documents service in this stack"
)

from app.core import storage as storage_module  # noqa: E402
from app.core.storage import FilesystemStorage  # noqa: E402
from app.services.documents.models import DocumentPage  # noqa: E402
from app.services.system.models import ComponentStatus  # noqa: E402
from tests.web.dom import location, one, select, text  # noqa: E402
from tests.web.overseer import sign_in, status_with  # noqa: E402

PAGE = "/overseer/services/documents"
PARTIALS = "/partials/overseer/documents"
DOCUMENTS = ComponentStatus(name="documents", message="Documents ready")


@pytest.fixture
def docs(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    async_client_with_db: TestClient,
) -> Generator[TestClient]:
    """Signed in, on the test's own session, with a store in a temp dir."""
    sign_in(app, monkeypatch, status_with(services=[DOCUMENTS]))
    storage_module.set_storage(FilesystemStorage(str(tmp_path)))
    yield async_client_with_db
    storage_module.set_storage(None)


def _get(client: TestClient, section: str = "", query: str = "") -> str:
    url = PAGE + (f"/{section}" if section else "") + (f"?{query}" if query else "")
    response = client.get(url)
    assert response.status_code == 200, response.text
    return response.text


def _upload(
    client: TestClient, name: str, data: bytes = b"%PDF-1.4 x", kind: str = "letter"
) -> int:
    response = client.post(
        f"{PARTIALS}/upload",
        data={"kind": kind},
        files={"file": (name, data, "application/pdf")},
    )
    assert response.status_code == 200, response.text
    path = location(response)
    return int(parse_qs(urlparse(path).query)["document"][0])


def _titles(html: str) -> list[str]:
    return [text(select(r, "td")[0]) for r in select(html, "#documents-list tbody tr")]


def test_sections(docs: TestClient) -> None:
    assert [text(a) for a in select(_get(docs), "#overseer-subnav nav a")] == [
        "Overview",
        "Documents",
        "Activity",
        "Tags",
    ]


def test_an_upload_is_filed_and_listed(docs: TestClient) -> None:
    _upload(docs, "bank-statement.pdf", kind="statement")
    html = _get(docs, "documents")
    assert _titles(html) == ["bank-statement.pdf"]
    assert "statement" in text(one(html, "#documents-list tbody tr"))


def test_the_same_bytes_are_filed_once(docs: TestClient) -> None:
    first = _upload(docs, "a.pdf", data=b"same bytes")
    assert _upload(docs, "b.pdf", data=b"same bytes") == first
    assert len(_titles(_get(docs, "documents"))) == 1


def test_the_list_narrows_by_kind_and_search(docs: TestClient) -> None:
    _upload(docs, "electric-bill.pdf", data=b"1", kind="statement")
    _upload(docs, "lease.pdf", data=b"2", kind="letter")
    assert _titles(_get(docs, "documents", "kind=letter")) == ["lease.pdf"]
    assert _titles(_get(docs, "documents", "q=electric")) == ["electric-bill.pdf"]


def _drawer(client: TestClient, doc: int) -> str:
    response = client.get(f"{PARTIALS}/{doc}/drawer")
    assert response.status_code == 200, response.text
    return response.text


def test_a_document_opens_in_the_drawer(docs: TestClient) -> None:
    doc = _upload(docs, "passport.pdf", kind="identification")
    html = _drawer(docs, doc)
    assert one(html, "input[name=title]").get("value") == "passport.pdf"
    assert "identification" in text(one(html, "#document-facts"))


def test_the_list_says_which_drawer_is_open(docs: TestClient) -> None:
    """The URL holds the open document, so a reload or a shared link opens
    the same drawer, and a list without one closes it."""
    doc = _upload(docs, "lease.pdf")
    sync = one(_get(docs, "documents", f"document={doc}"), "[data-drawer-sync]")
    assert sync.get("data-drawer-url") == f"{PARTIALS}/{doc}/drawer"
    assert sync.get("data-drawer-param") == "document"
    assert not one(_get(docs, "documents"), "[data-drawer-sync]").get("data-drawer-url")


def test_a_row_opens_its_document(docs: TestClient) -> None:
    doc = _upload(docs, "deed.pdf")
    link = one(_get(docs, "documents", "kind=letter"), "#documents-list tbody a")
    assert f"document={doc}" in link.get("href") and "kind=letter" in link.get("href")


async def _stored_page(session: AsyncSession, doc: int, tmp_path: Path) -> None:
    """Page 1 as extraction leaves it: a render in the store and its text."""
    key = await storage_module.get_storage().put(b"PNGDATA", content_type="image/png")
    session.add(
        DocumentPage(
            document_id=doc,
            page_number=1,
            status="read",
            text="Hello page",
            image_key=key,
        )
    )
    await session.commit()


async def test_pages_show_as_thumbnails(
    docs: TestClient, async_db_session: AsyncSession, tmp_path: Path
) -> None:
    doc = _upload(docs, "scan.pdf")
    await _stored_page(async_db_session, doc, tmp_path)
    thumb = one(_drawer(docs, doc), "#document-pages img")
    assert thumb.get("src") == f"{PARTIALS}/{doc}/pages/1/image"


async def test_a_page_image_comes_from_the_store(
    docs: TestClient, async_db_session: AsyncSession, tmp_path: Path
) -> None:
    doc = _upload(docs, "scan.pdf")
    await _stored_page(async_db_session, doc, tmp_path)
    response = docs.get(f"{PARTIALS}/{doc}/pages/1/image")
    assert response.status_code == 200 and response.content == b"PNGDATA"


async def test_a_page_preview_shows_the_image_beside_its_text(
    docs: TestClient, async_db_session: AsyncSession, tmp_path: Path
) -> None:
    doc = _upload(docs, "scan.pdf")
    await _stored_page(async_db_session, doc, tmp_path)
    html = docs.get(f"{PARTIALS}/{doc}/pages/1").text
    assert one(html, "img").get("src") == f"{PARTIALS}/{doc}/pages/1/image"
    assert "Hello page" in text(one(html, "[data-card]"))


def test_activity_lists_extraction_runs(
    docs: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.components.web_frontend import overseer_documents
    from app.services.system.jobs import JobSnapshot

    doc = _upload(docs, "bill.pdf")

    class Runner:
        async def list_all(self) -> list[JobSnapshot]:
            return [
                JobSnapshot(
                    job_id="j1",
                    name=f"documents-extract:{doc}",
                    status="done",
                    label="",
                    result={"read": 3, "unread": 0},
                    error=None,
                ),
                JobSnapshot("j2", "finance-import", "done", "", {}, None),
            ]

    monkeypatch.setattr(overseer_documents, "get_job_runner", lambda: Runner())
    rows = select(_get(docs, "activity"), "#documents-activity tbody tr")
    assert len(rows) == 1
    assert "bill.pdf" in text(rows[0]) and "3 pages extracted" in text(rows[0])


def test_saving_changes_the_title_and_kind(docs: TestClient) -> None:
    doc = _upload(docs, "scan.pdf")
    response = docs.post(
        f"{PARTIALS}/{doc}",
        data={"title": "Lease 2026", "kind": "form", "document_date": "", "note": ""},
    )
    assert response.status_code == 200, response.text
    assert _titles(_get(docs, "documents")) == ["Lease 2026"]


def test_tags_are_added_and_removed(docs: TestClient) -> None:
    doc = _upload(docs, "tax.pdf")
    assert (
        docs.post(f"{PARTIALS}/{doc}/tags", data={"label": "taxes"}).status_code == 200
    )
    assert "taxes" in text(one(_drawer(docs, doc), "#document-tags"))
    assert _titles(_get(docs, "documents", "tag=taxes")) == ["tax.pdf"]
    assert docs.delete(f"{PARTIALS}/{doc}/tags/taxes").status_code == 204
    assert "taxes" not in text(one(_drawer(docs, doc), "#document-tags"))


def test_a_document_downloads(docs: TestClient) -> None:
    doc = _upload(docs, "receipt.pdf", data=b"%PDF-1.4 receipt")
    response = docs.get(f"{PARTIALS}/{doc}/download")
    assert response.status_code == 200 and response.content == b"%PDF-1.4 receipt"
    assert 'filename="receipt.pdf"' in response.headers["content-disposition"]


def test_deleting_retires_the_document(docs: TestClient) -> None:
    doc = _upload(docs, "old.pdf")
    assert select(
        docs.get(f"{PARTIALS}/{doc}/confirm-delete").text, "button[hx-delete]"
    )
    assert docs.delete(f"{PARTIALS}/{doc}").status_code == 204
    assert _titles(_get(docs, "documents")) == []


def test_reading_hands_the_document_to_extraction(
    docs: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.components.web_frontend.routes.partials import overseer_documents

    started: list[int] = []

    async def start(document_id: int, *, owner_user_id: int | None, force: bool) -> str:
        started.append(document_id)
        return "job-1"

    monkeypatch.setattr(overseer_documents, "start_extraction", start)
    doc = _upload(docs, "letter.pdf")
    assert docs.post(f"{PARTIALS}/{doc}/read").status_code == 200
    assert started == [doc]


def test_the_overview_counts_what_is_on_file(docs: TestClient) -> None:
    _upload(docs, "one.pdf", data=b"1", kind="letter")
    _upload(docs, "two.pdf", data=b"2", kind="statement")
    figures = {
        text(one(cell, "dt")): text(select(cell, "dd")[0])
        for cell in select(_get(docs), "#documents-figures > div")
    }
    assert figures["Documents"] == "2"
