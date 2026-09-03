"""The jobs API lists every job, not only the one you asked about."""

from fastapi.testclient import TestClient
import pytest

from app.components.backend.api.documents import pages
from app.core.storage import FilesystemStorage, set_storage
from app.services.documents.domains.extraction import dispatch
from tests._jobs import wait_for_job
from tests._pdf import pdf_bytes


@pytest.fixture(autouse=True)
def _storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    set_storage(FilesystemStorage(tmp_path))
    async def _no_vision() -> None:
        return None

    monkeypatch.setattr(pages, "vision_reader", _no_vision)
    monkeypatch.setattr(pages, "start_extraction", dispatch.start_extraction_in_process)
    yield
    set_storage(None)


def _extract_in_background(client: TestClient, title: str) -> str:
    created = client.post(
        "/api/v1/documents",
        files={
            "file": (
                f"{title}.pdf",
                pdf_bytes([f"{title} page one"]),
                "application/pdf",
            )
        },
        data={"title": title},
    ).json()
    started = client.post(f"/api/v1/documents/{created['id']}/extract?background=true")
    assert started.status_code == 202
    return str(started.json()["job_id"])


def test_every_job_is_listed_with_when_it_started(client: TestClient) -> None:
    first = _extract_in_background(client, "Jobs list one")
    # In-process extraction writes from its own session; on SQLite a second
    # extraction starting mid-flight is a second writer, and the store locks.
    wait_for_job(client, first)
    second = _extract_in_background(client, "Jobs list two")
    wait_for_job(client, second)

    listed = client.get("/api/v1/jobs")

    assert listed.status_code == 200
    rows = {row["job_id"]: row for row in listed.json()}
    assert first in rows and second in rows
    assert rows[first]["name"].startswith("documents-extract:")
    assert (
        rows[first]["started_at"]
        and rows[second]["started_at"] >= rows[first]["started_at"]
    )
