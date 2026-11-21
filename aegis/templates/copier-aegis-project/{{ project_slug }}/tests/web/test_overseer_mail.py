"""The Overseer Documents page's Mail section: the mailbox the app pulls,
and what came in and what each message became.

Both render paths; selectors. The rows are the same ``arrivals`` the
assistant's tool reads, so the page asserts each row's own ``became``
rather than restating the sentence.
"""

from collections.abc import Iterator
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

pytest.importorskip("app.services.mail", reason="no documents service in this stack")

from app.core.db import OpenSession  # noqa: E402
from app.core.storage import FilesystemStorage  # noqa: E402
from app.services.mail import ingest, pull  # noqa: E402
from app.services.mail.arrivals import Arrival, arrivals  # noqa: E402
from app.services.system.models import ComponentStatus  # noqa: E402
from tests._mbox import PDF, mbox_bytes, message  # noqa: E402
from tests._secret_settings import secret_settings  # noqa: E402
from tests.web.dom import none, one, table_rows, text  # noqa: E402
from tests.web.overseer import sign_in, status_with  # noqa: E402

pytestmark = pytest.mark.usefixtures("no_mail_hooks")

PAGE = "/overseer/services/documents"
MAIL = f"{PAGE}/mail"
DOCUMENTS = ComponentStatus(name="documents", message="Documents ready")
HX = {"HX-Request": "true"}
SECRETS = (pull.HOST, pull.USER, pull.FOLDER, pull.PASSWORD)


@pytest.fixture
def docs(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    files: FilesystemStorage,
    async_client_with_db: TestClient,
) -> Iterator[TestClient]:
    """Signed in, on the test's own session, with no mailbox named."""
    sign_in(app, monkeypatch, status_with(services=[DOCUMENTS]))
    with secret_settings(*SECRETS):
        yield async_client_with_db


@pytest.fixture
async def arrived(
    async_db_session: AsyncSession, open_session: OpenSession, dispatched: list[int]
) -> dict[str, Arrival]:
    """A statement with an attachment, a letter, and an empty newsletter."""
    data = mbox_bytes(
        [
            message(
                subject="Your statement",
                attachments=[("statement.pdf", "application/pdf", PDF)],
            ),
            message(sender="County <intake@county.example>", subject="Renewal notice"),
            message(sender="News <news@shop.example>", subject="Weekly deals", body=""),
        ]
    )
    await ingest.ingest_mail(open_session, data=data, file_name="export.mbox")
    [day] = await arrivals(async_db_session, owner_user_id=None)
    return {row.subject: row for row in day.messages}


def _get(client: TestClient, htmx: bool = False) -> str:
    response = client.get(MAIL, headers=HX if htmx else {})
    assert response.status_code == 200, response.text
    return response.text


def _rows(html: str, day: Any) -> dict[str, Any]:
    table = one(html, f"#mail-day-{day.isoformat()} table")
    return {text(row["Subject"]): row for row in table_rows(table)}


@pytest.mark.parametrize("htmx", [False, True], ids=["cold", "htmx"])
def test_what_came_in_and_what_it_became(
    docs: TestClient, arrived: dict[str, Arrival], htmx: bool
) -> None:
    html = _get(docs, htmx)
    (none if htmx else one)(html, "html")
    statement = arrived["Your statement"]
    rows = _rows(html, statement.received_at.date())

    assert set(rows) == set(arrived)
    for subject, row in rows.items():
        assert text(row["Became"]) == arrived[subject].became
    assert text(rows["Your statement"]["From"]) == statement.sender


def test_a_subject_opens_its_letter_and_an_attachment_its_document(
    docs: TestClient, arrived: dict[str, Arrival]
) -> None:
    statement = arrived["Your statement"]
    rows = _rows(_get(docs), statement.received_at.date())
    row = rows["Your statement"]

    letter = one(row["Subject"], "a")
    assert letter.get("href") == f"{PAGE}/documents?document={statement.letter_id}"
    paper = one(row["Attachments"], "a")
    assert text(paper) == "statement.pdf"
    assert paper.get("href") == (
        f"{PAGE}/documents?document={statement.attachments[0].document_id}"
    )
    # A message that filed nothing has nothing to open.
    none(rows["Weekly deals"]["Subject"], "a")


def test_no_mail_says_so(docs: TestClient) -> None:
    html = _get(docs)
    one(html, "#mail-arrivals [data-empty]")
    none(html, "#mail-arrivals table")


def test_no_mailbox_no_line(docs: TestClient) -> None:
    none(_get(docs), "[data-mailbox]")


def test_a_named_mailbox_says_it_has_not_been_pulled_yet(docs: TestClient) -> None:
    with secret_settings(*SECRETS) as s:
        s.MAIL_IMAP_HOST, s.MAIL_IMAP_USER = "imap.example.com", "sam@example.com"
        s.MAIL_IMAP_FOLDER, s.MAIL_IMAP_PASSWORD = "Receipts", "abcd efgh ijkl mnop"
        line = one(_get(docs), "[data-mailbox]")
    assert "sam@example.com / Receipts" in text(line)
    assert "nothing pulled yet" in text(line)
