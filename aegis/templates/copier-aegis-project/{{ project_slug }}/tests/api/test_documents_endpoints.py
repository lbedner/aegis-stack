"""The document store's HTTP surface.

Upload is idempotent because storage keys are content-derived, which is
the property a retrying client depends on: the same file twice is one
document, not two.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.storage import FilesystemStorage, set_storage


@pytest.fixture(autouse=True)
def _storage(tmp_path):
    set_storage(FilesystemStorage(tmp_path))
    yield
    set_storage(None)


class TestDocumentEndpoints:
    def test_upload_stores_the_file_and_returns_it(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/documents",
            files={"file": ("scan.pdf", b"%PDF-1.7 scan", "application/pdf")},
            data={"title": "Renewal request", "kind": "letter"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["title"] == "Renewal request"
        assert body["storage_key"].startswith("sha256/")
        assert body["byte_size"] == len(b"%PDF-1.7 scan")

    def test_uploading_the_same_file_twice_is_one_document(
        self, client: TestClient
    ) -> None:
        """A retried upload must not double the file cabinet."""
        payload = b"identical bytes for the retry case"
        first = client.post(
            "/api/v1/documents",
            files={"file": ("scan.pdf", payload, "application/pdf")},
            data={"title": "S", "kind": "identification"},
        )
        second = client.post(
            "/api/v1/documents",
            files={"file": ("scan.pdf", payload, "application/pdf")},
            data={"title": "S", "kind": "identification"},
        )

        assert first.json()["id"] == second.json()["id"]
        # Scoped by kind rather than counting everything: this store is
        # shared with whatever else the suite has filed.
        listed = client.get("/api/v1/documents", params={"kind": "identification"})
        assert listed.json()["total"] == 1

    def test_download_returns_the_stored_bytes(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/documents",
            files={"file": ("a.txt", b"the bytes", "text/plain")},
            data={"title": "A"},
        ).json()

        response = client.get(f"/api/v1/documents/{created['id']}/content")

        assert response.status_code == 200
        assert response.content == b"the bytes"

    def test_an_unknown_kind_is_a_client_error(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/documents",
            files={"file": ("a.txt", b"x", "text/plain")},
            data={"title": "A", "kind": "invoice-ish"},
        )

        assert response.status_code == 400
        assert "kind" in response.json()["detail"]

    def test_tagging_then_filtering_finds_it(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/documents",
            files={"file": ("a.txt", b"tagged", "text/plain")},
            data={"title": "Tagged"},
        ).json()
        client.post(
            "/api/v1/documents",
            files={"file": ("b.txt", b"untagged", "text/plain")},
            data={"title": "Untagged"},
        )

        client.post(
            f"/api/v1/documents/{created['id']}/tags", json={"label": "medicaid"}
        )
        listed = client.get("/api/v1/documents", params={"tag": "medicaid"}).json()

        assert listed["total"] == 1
        assert listed["items"][0]["tags"] == ["medicaid"]

    def test_a_missing_document_is_a_404(self, client: TestClient) -> None:
        assert client.get("/api/v1/documents/9999").status_code == 404

    def test_delete_retires_it(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/documents",
            files={"file": ("a.txt", b"gone", "text/plain")},
            data={"title": "Old"},
        ).json()

        assert client.delete(f"/api/v1/documents/{created['id']}").status_code == 204
        assert client.get(f"/api/v1/documents/{created['id']}").status_code == 404

    def test_a_deduped_upload_says_so_with_200_not_201(
        self, client: TestClient
    ) -> None:
        """The UI tells the user "already stored" instead of pretending a
        second copy landed - the status code is how it knows."""
        payload = b"bytes the client will send twice"
        first = client.post(
            "/api/v1/documents",
            files={"file": ("scan.pdf", payload, "application/pdf")},
            data={"title": "S", "kind": "receipt"},
        )
        second = client.post(
            "/api/v1/documents",
            files={"file": ("scan.pdf", payload, "application/pdf")},
            data={"title": "S", "kind": "receipt"},
        )

        assert first.status_code == 201
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]

    def test_patch_renames_and_dates_the_paper(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/documents",
            files={"file": ("a.txt", b"patch me", "text/plain")},
            data={"title": "Untitled"},
        ).json()

        response = client.patch(
            f"/api/v1/documents/{created['id']}",
            json={
                "title": "Renewal request",
                "kind": "letter",
                "document_date": "2026-08-27",
                "note": "Due Sep 8",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["title"] == "Renewal request"
        assert body["kind"] == "letter"
        assert body["document_date"] == "2026-08-27"
        assert body["note"] == "Due Sep 8"

    def test_patch_with_a_bad_kind_is_a_client_error(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/documents",
            files={"file": ("a.txt", b"bad kind", "text/plain")},
            data={"title": "A"},
        ).json()

        response = client.patch(
            f"/api/v1/documents/{created['id']}", json={"kind": "invoice-ish"}
        )

        assert response.status_code == 400

    def test_tags_lists_labels_with_counts(self, client: TestClient) -> None:
        a = client.post(
            "/api/v1/documents",
            files={"file": ("a.txt", b"tag count a", "text/plain")},
            data={"title": "A"},
        ).json()
        b = client.post(
            "/api/v1/documents",
            files={"file": ("b.txt", b"tag count b", "text/plain")},
            data={"title": "B"},
        ).json()
        client.post(f"/api/v1/documents/{a['id']}/tags", json={"label": "estate"})
        client.post(f"/api/v1/documents/{b['id']}/tags", json={"label": "estate"})

        response = client.get("/api/v1/documents/tags")

        assert response.status_code == 200
        by_label = {row["label"]: row["count"] for row in response.json()}
        assert by_label["estate"] == 2

    def test_untag_removes_the_label(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/documents",
            files={"file": ("a.txt", b"untag me", "text/plain")},
            data={"title": "A"},
        ).json()
        client.post(f"/api/v1/documents/{created['id']}/tags", json={"label": "tmp"})

        response = client.delete(f"/api/v1/documents/{created['id']}/tags/tmp")

        assert response.status_code == 200
        assert response.json()["tags"] == []
        assert (
            client.delete(f"/api/v1/documents/{created['id']}/tags/tmp").status_code
            == 404
        )
