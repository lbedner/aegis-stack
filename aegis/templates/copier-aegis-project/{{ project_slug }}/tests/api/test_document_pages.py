"""The extraction surface: kick it off, then read pages back."""

from fastapi.testclient import TestClient
import pytest

from app.components.backend.api.documents import pages
from app.core.storage import FilesystemStorage, set_storage
from tests._pdf import pdf_bytes


@pytest.fixture(autouse=True)
def _storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    set_storage(FilesystemStorage(tmp_path))
    # No model in the test process: scans come back unread, deterministically.
    monkeypatch.setattr(pages, "vision_reader", lambda: None)
    yield
    set_storage(None)


def _upload(client: TestClient, texts: list[str], title: str) -> int:
    # The title rides in the text so two tests never dedupe onto one row.
    texts = [f"{text} for {title}" if text else "" for text in texts]
    created = client.post(
        "/api/v1/documents",
        files={"file": (f"{title}.pdf", pdf_bytes(texts), "application/pdf")},
        data={"title": title, "kind": "letter"},
    )
    assert created.status_code in (200, 201)
    return int(created.json()["id"])


class TestExtraction:
    def test_extract_reads_the_text_layer_and_reports(self, client: TestClient) -> None:
        doc_id = _upload(
            client, ["Renewal request received", "Page two of the same"], "Renewal"
        )

        response = client.post(f"/api/v1/documents/{doc_id}/extract")

        assert response.status_code == 200
        body = response.json()
        assert body["read"] == 2 and body["unread"] == 0

    def test_pages_list_carries_status_not_text(self, client: TestClient) -> None:
        doc_id = _upload(client, ["Alpha page with text", ""], "Mixed")
        client.post(f"/api/v1/documents/{doc_id}/extract")

        pages = client.get(f"/api/v1/documents/{doc_id}/pages").json()

        assert [p["page_number"] for p in pages] == [1, 2]
        assert pages[0]["status"] == "read" and pages[1]["status"] == "unread"
        assert "text" not in pages[0]
        assert pages[0]["has_image"] is True

    def test_one_page_carries_its_text_and_image(self, client: TestClient) -> None:
        doc_id = _upload(client, ["Alpha page with text"], "Single")
        client.post(f"/api/v1/documents/{doc_id}/extract")

        page = client.get(f"/api/v1/documents/{doc_id}/pages/1")
        image = client.get(f"/api/v1/documents/{doc_id}/pages/1/image")

        assert page.status_code == 200 and "Alpha" in page.json()["text"]
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        assert image.content[:8] == b"\x89PNG\r\n\x1a\n"

    def test_a_missing_page_is_a_404(self, client: TestClient) -> None:
        doc_id = _upload(client, ["Alpha page with text"], "Short")
        client.post(f"/api/v1/documents/{doc_id}/extract")

        assert client.get(f"/api/v1/documents/{doc_id}/pages/7").status_code == 404

    def test_background_returns_a_job(self, client: TestClient) -> None:
        doc_id = _upload(client, ["Alpha page with text"], "Job")

        response = client.post(f"/api/v1/documents/{doc_id}/extract?background=true")

        assert response.status_code == 202
        job_id = response.json()["job_id"]
        # Drive the job to its end here: the runner's task only advances
        # while the test client is inside a request, and a job left
        # running would hold the shared test database into the next test.
        for _ in range(50):
            body = client.get(f"/api/v1/jobs/{job_id}").json()
            if body["status"] != "running":
                break
        assert body["status"] == "done", body
        assert body["result"]["read"] == 1
