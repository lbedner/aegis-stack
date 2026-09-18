"""The document store's HTTP surface.

Upload is idempotent because storage keys are content-derived, which is
the property a retrying client depends on: the same file twice is one
document, not two.

Requests go through ``authenticated_app_client`` rather than ``client``
because these routes sit behind the auth dependency whenever the auth
service is present, and this suite ships in stacks with and without it.
That conftest fixture already resolves both: it signs as the seeded
user when there is auth to satisfy, and is a passthrough when there is
not — so the suite needs no branch of its own. It is the ``_app_``
variant because extraction hands work to a background job on its own
session, which cannot see rows written inside a test transaction.
"""

from fastapi.testclient import TestClient
import pytest

from app.core.storage import FilesystemStorage, set_storage


@pytest.fixture(autouse=True)
def _storage(tmp_path):
    set_storage(FilesystemStorage(tmp_path))
    yield
    set_storage(None)


class TestDocumentEndpoints:
    def test_upload_stores_the_file_and_returns_it(self, authenticated_app_client: TestClient) -> None:
        response = authenticated_app_client.post(
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
        self, authenticated_app_client: TestClient
    ) -> None:
        """A retried upload must not double the file cabinet."""
        payload = b"identical bytes for the retry case"
        first = authenticated_app_client.post(
            "/api/v1/documents",
            files={"file": ("scan.pdf", payload, "application/pdf")},
            data={"title": "S", "kind": "identification"},
        )
        second = authenticated_app_client.post(
            "/api/v1/documents",
            files={"file": ("scan.pdf", payload, "application/pdf")},
            data={"title": "S", "kind": "identification"},
        )

        assert first.json()["id"] == second.json()["id"]
        # Scoped by kind rather than counting everything: this store is
        # shared with whatever else the suite has filed.
        listed = authenticated_app_client.get("/api/v1/documents", params={"kind": "identification"})
        assert listed.json()["total"] == 1

    def test_download_returns_the_stored_bytes(self, authenticated_app_client: TestClient) -> None:
        created = authenticated_app_client.post(
            "/api/v1/documents",
            files={"file": ("a.txt", b"the bytes", "text/plain")},
            data={"title": "A"},
        ).json()

        response = authenticated_app_client.get(f"/api/v1/documents/{created['id']}/content")

        assert response.status_code == 200
        assert response.content == b"the bytes"

    def test_an_unknown_kind_is_a_client_error(self, authenticated_app_client: TestClient) -> None:
        response = authenticated_app_client.post(
            "/api/v1/documents",
            files={"file": ("a.txt", b"x", "text/plain")},
            data={"title": "A", "kind": "invoice-ish"},
        )

        assert response.status_code == 400
        assert "kind" in response.json()["detail"]

    def test_tagging_then_filtering_finds_it(self, authenticated_app_client: TestClient) -> None:
        created = authenticated_app_client.post(
            "/api/v1/documents",
            files={"file": ("a.txt", b"tagged", "text/plain")},
            data={"title": "Tagged"},
        ).json()
        authenticated_app_client.post(
            "/api/v1/documents",
            files={"file": ("b.txt", b"untagged", "text/plain")},
            data={"title": "Untagged"},
        )

        authenticated_app_client.post(
            f"/api/v1/documents/{created['id']}/tags", json={"label": "medicaid"}
        )
        listed = authenticated_app_client.get("/api/v1/documents", params={"tag": "medicaid"}).json()

        assert listed["total"] == 1
        assert listed["items"][0]["tags"] == ["medicaid"]

    def test_a_missing_document_is_a_404(self, authenticated_app_client: TestClient) -> None:
        assert authenticated_app_client.get("/api/v1/documents/9999").status_code == 404

    def test_delete_retires_it(self, authenticated_app_client: TestClient) -> None:
        created = authenticated_app_client.post(
            "/api/v1/documents",
            files={"file": ("a.txt", b"gone", "text/plain")},
            data={"title": "Old"},
        ).json()

        assert authenticated_app_client.delete(f"/api/v1/documents/{created['id']}").status_code == 204
        assert authenticated_app_client.get(f"/api/v1/documents/{created['id']}").status_code == 404

    def test_a_deduped_upload_says_so_with_200_not_201(
        self, authenticated_app_client: TestClient
    ) -> None:
        """The UI tells the user "already stored" instead of pretending a
        second copy landed - the status code is how it knows."""
        payload = b"bytes the client will send twice"
        first = authenticated_app_client.post(
            "/api/v1/documents",
            files={"file": ("scan.pdf", payload, "application/pdf")},
            data={"title": "S", "kind": "receipt"},
        )
        second = authenticated_app_client.post(
            "/api/v1/documents",
            files={"file": ("scan.pdf", payload, "application/pdf")},
            data={"title": "S", "kind": "receipt"},
        )

        assert first.status_code == 201
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]

    def test_patch_renames_and_dates_the_paper(self, authenticated_app_client: TestClient) -> None:
        created = authenticated_app_client.post(
            "/api/v1/documents",
            files={"file": ("a.txt", b"patch me", "text/plain")},
            data={"title": "Untitled"},
        ).json()

        response = authenticated_app_client.patch(
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

    def test_patch_with_a_bad_kind_is_a_client_error(self, authenticated_app_client: TestClient) -> None:
        created = authenticated_app_client.post(
            "/api/v1/documents",
            files={"file": ("a.txt", b"bad kind", "text/plain")},
            data={"title": "A"},
        ).json()

        response = authenticated_app_client.patch(
            f"/api/v1/documents/{created['id']}", json={"kind": "invoice-ish"}
        )

        assert response.status_code == 400

    def test_tags_lists_labels_with_counts(self, authenticated_app_client: TestClient) -> None:
        a = authenticated_app_client.post(
            "/api/v1/documents",
            files={"file": ("a.txt", b"tag count a", "text/plain")},
            data={"title": "A"},
        ).json()
        b = authenticated_app_client.post(
            "/api/v1/documents",
            files={"file": ("b.txt", b"tag count b", "text/plain")},
            data={"title": "B"},
        ).json()
        authenticated_app_client.post(f"/api/v1/documents/{a['id']}/tags", json={"label": "estate"})
        authenticated_app_client.post(f"/api/v1/documents/{b['id']}/tags", json={"label": "estate"})

        response = authenticated_app_client.get("/api/v1/documents/tags")

        assert response.status_code == 200
        by_label = {row["label"]: row["count"] for row in response.json()}
        assert by_label["estate"] == 2

    def test_untag_removes_the_label(self, authenticated_app_client: TestClient) -> None:
        created = authenticated_app_client.post(
            "/api/v1/documents",
            files={"file": ("a.txt", b"untag me", "text/plain")},
            data={"title": "A"},
        ).json()
        authenticated_app_client.post(f"/api/v1/documents/{created['id']}/tags", json={"label": "tmp"})

        response = authenticated_app_client.delete(f"/api/v1/documents/{created['id']}/tags/tmp")

        assert response.status_code == 200
        assert response.json()["tags"] == []
        assert (
            authenticated_app_client.delete(f"/api/v1/documents/{created['id']}/tags/tmp").status_code
            == 404
        )

    def test_a_protected_document_refuses_a_bare_delete(
        self, authenticated_app_client: TestClient
    ) -> None:
        created = authenticated_app_client.post(
            "/api/v1/documents",
            files={"file": ("poa.pdf", b"executed poa bytes", "application/pdf")},
            data={"title": "Executed POA"},
        ).json()
        authenticated_app_client.patch(f"/api/v1/documents/{created['id']}", json={"protected": True})

        assert authenticated_app_client.delete(f"/api/v1/documents/{created['id']}").status_code == 409
        assert (
            authenticated_app_client.delete(
                f"/api/v1/documents/{created['id']}", params={"confirm": "wrong"}
            ).status_code
            == 409
        )
        assert (
            authenticated_app_client.delete(
                f"/api/v1/documents/{created['id']}",
                params={"confirm": "Executed POA"},
            ).status_code
            == 204
        )

    def test_superseded_documents_leave_the_default_listing(
        self, authenticated_app_client: TestClient
    ) -> None:
        draft = authenticated_app_client.post(
            "/api/v1/documents",
            files={"file": ("d.pdf", b"draft bytes", "application/pdf")},
            data={"title": "Draft", "kind": "form"},
        ).json()
        final = authenticated_app_client.post(
            "/api/v1/documents",
            files={"file": ("f.pdf", b"final bytes", "application/pdf")},
            data={"title": "Final", "kind": "form"},
        ).json()

        patched = authenticated_app_client.patch(
            f"/api/v1/documents/{final['id']}", json={"supersedes_id": draft["id"]}
        )

        assert patched.status_code == 200
        assert patched.json()["supersedes_id"] == draft["id"]
        titles = [
            d["title"]
            for d in authenticated_app_client.get("/api/v1/documents", params={"kind": "form"}).json()[
                "items"
            ]
        ]
        assert titles == ["Final"]
        both = authenticated_app_client.get(
            "/api/v1/documents", params={"kind": "form", "include_superseded": True}
        ).json()
        assert both["total"] == 2

    def test_protected_cannot_be_unset_to_null(self, authenticated_app_client: TestClient) -> None:
        created = authenticated_app_client.post(
            "/api/v1/documents",
            files={"file": ("n.pdf", b"null protected", "application/pdf")},
            data={"title": "N"},
        ).json()

        response = authenticated_app_client.patch(
            f"/api/v1/documents/{created['id']}", json={"protected": None}
        )

        assert response.status_code == 400
        assert (
            authenticated_app_client.get(f"/api/v1/documents/{created['id']}").json()["protected"]
            is False
        )

    def test_channel_is_filed_and_filterable(self, authenticated_app_client: TestClient) -> None:
        authenticated_app_client.post(
            "/api/v1/documents",
            files={"file": ("m.pdf", b"mailed bytes", "application/pdf")},
            data={"title": "Mailed", "channel": "mail"},
        )

        listed = authenticated_app_client.get("/api/v1/documents", params={"channel": "mail"}).json()

        assert listed["total"] == 1
        assert listed["items"][0]["channel"] == "mail"
