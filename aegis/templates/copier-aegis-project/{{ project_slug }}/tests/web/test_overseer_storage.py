"""The Overseer Storage page: an Overview of the app's bucket (how much it
holds, at what sizes, and how the app reaches it), and a Browse section
that opens any bucket folder by folder."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.core import storage as storage_module
from app.services.system.models import ComponentStatus, ComponentStatusType
from tests.web.dom import one, select, text
from tests.web.overseer import sign_in, status_with

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
DIGEST = "0123456789abcdef" * 4


def _object(size: int, minutes_ago: int, digest: str = DIGEST) -> dict[str, Any]:
    return {
        "key": f"sha256/{digest[:2]}/{digest[2:4]}/{digest}",
        "size": size,
        "modified": NOW - timedelta(minutes=minutes_ago),
    }


class FakeBucket:
    backend_name = "s3"
    bucket = "my-app"

    def __init__(self, objects: list[dict[str, Any]], truncated: bool = False) -> None:
        self.objects, self.truncated = objects, truncated
        self.files: dict[tuple[str, str], tuple[bytes, str | None]] = {
            ("demo-files", "README.md"): (b"# demo", "text/markdown"),
            ("my-app", "README.md"): (b"# app", "text/markdown"),
        }

    async def fetch(self, bucket: str, key: str) -> tuple[bytes, str | None] | None:
        return self.files.get((bucket, key))

    async def remove(self, bucket: str, key: str) -> bool:
        return self.files.pop((bucket, key), None) is not None

    async def remove_many(self, bucket: str, keys: list[str]) -> None:
        for key in keys:
            self.files.pop((bucket, key), None)

    async def upload(
        self, bucket: str, key: str, data: bytes, content_type: str | None
    ) -> None:
        self.files[(bucket, key)] = (data, content_type)

    async def list_objects(self, limit: int) -> tuple[list[dict[str, Any]], bool]:
        return self.objects[:limit], self.truncated

    async def buckets(self) -> list[dict[str, Any]]:
        return [
            {"name": "demo-files", "created": NOW},
            {"name": "my-app", "created": NOW},
        ]

    async def browse(
        self, bucket: str, prefix: str, limit: int = 1000
    ) -> dict[str, Any]:
        if bucket == "missing":
            raise ValueError("NoSuchBucket: missing")
        tree = {
            "": (["invoices/"], ["README.md"]),
            "invoices/": (["invoices/2026-09/"], ["invoices/x.pdf"]),
        }
        folders, files = tree.get(prefix, ([], []))
        return {
            "folders": folders,
            "files": [{"key": k, "size": 1200, "modified": NOW} for k in files],
            "truncated": False,
        }


class BrokenBucket(FakeBucket):
    async def list_objects(self, limit: int) -> tuple[list[dict[str, Any]], bool]:
        raise ConnectionError("seaweedfs:8333 refused")


STORAGE = ComponentStatus(
    name="storage",
    status=ComponentStatusType.HEALTHY,
    message="Bucket my-app reachable",
    metadata={
        "backend": "s3",
        "endpoint": "seaweedfs:8333",
        "bucket": "my-app",
        "region": "us-east-1",
    },
)


@pytest.fixture
def signed_in(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    sign_in(app, monkeypatch, status_with(STORAGE))
    with TestClient(app) as client:
        yield client
    storage_module.set_storage(None)


def _get(client: TestClient, bucket: Any, section: str = "") -> str:
    storage_module.set_storage(bucket)
    response = client.get(
        "/overseer/components/storage" + (f"/{section}" if section else "")
    )
    assert response.status_code == 200
    return response.text


def _figures(html: str) -> dict[str, str]:
    return {
        text(one(cell, "dt")): text(one(cell, "dd"))
        for cell in select(html, "#storage-figures > div")
    }


OBJECTS = [
    _object(512, 30, "aa" + DIGEST[2:]),
    _object(3 * 1024 * 1024, 5, "bb" + DIGEST[2:]),
    _object(20 * 1024, 60, "cc" + DIGEST[2:]),
]


def test_sections_are_overview_and_browse(signed_in: TestClient) -> None:
    html = _get(signed_in, FakeBucket(OBJECTS))
    assert [text(a) for a in select(html, "#overseer-subnav nav a")] == [
        "Overview",
        "Browse",
        "Container",
    ]


def test_overview_counts_the_bucket(signed_in: TestClient) -> None:
    figures = _figures(_get(signed_in, FakeBucket(OBJECTS)))
    assert figures["Objects"] == "3"
    assert figures["Largest"] == "3.0 MB"


def test_overview_names_the_connection(signed_in: TestClient) -> None:
    connection = text(one(_get(signed_in, FakeBucket(OBJECTS)), "#card-connection"))
    assert "seaweedfs:8333" in connection and "my-app" in connection


def test_overview_bands_by_size(signed_in: TestClient) -> None:
    bands = text(one(_get(signed_in, FakeBucket(OBJECTS)), "#storage-sizes"))
    assert "Under 1 KB" in bands and "1 MB to 10 MB" in bands


def test_a_capped_listing_says_the_numbers_are_a_floor(signed_in: TestClient) -> None:
    html = _get(signed_in, FakeBucket(OBJECTS, truncated=True))
    assert _figures(html)["Objects"] == "3+"


def test_an_empty_bucket_says_what_fills_it(signed_in: TestClient) -> None:
    html = _get(signed_in, FakeBucket([]))
    assert select(html, "[data-empty]")


def test_an_unreadable_bucket_shows_why(signed_in: TestClient) -> None:
    html = _get(signed_in, BrokenBucket([]))
    assert "refused" in text(one(html, "[role=alert]"))


def _browse(client: TestClient, query: str = "") -> str:
    return _get(client, FakeBucket(OBJECTS), "browse" + (f"?{query}" if query else ""))


def _names(html: str) -> list[str]:
    return [
        text(select(row, "td")[0]) for row in select(html, "#storage-browse tbody tr")
    ]


def test_browse_starts_with_the_buckets(signed_in: TestClient) -> None:
    assert _names(_browse(signed_in)) == ["demo-files", "my-app"]


def test_a_bucket_opens_on_its_folders_then_files(signed_in: TestClient) -> None:
    html = _browse(signed_in, "bucket=my-app")
    assert _names(html) == ["invoices/", "README.md"]
    assert [text(a) for a in select(html, "#storage-crumbs a")] == ["Buckets"]
    assert text(one(html, "#storage-crumbs [aria-current]")) == "my-app"


def test_a_folder_opens_one_level_down(signed_in: TestClient) -> None:
    html = _browse(signed_in, "bucket=my-app&prefix=invoices/")
    assert _names(html) == ["2026-09/", "x.pdf"]
    assert [text(a) for a in select(html, "#storage-crumbs a")] == ["Buckets", "my-app"]


def test_folders_link_one_level_deeper(signed_in: TestClient) -> None:
    link = one(
        _browse(signed_in, "bucket=my-app"), "#storage-browse tbody a[href*='prefix=']"
    )
    assert "prefix=invoices%2F" in link.get("href")


def test_a_bucket_that_cannot_be_read_says_why(signed_in: TestClient) -> None:
    html = _browse(signed_in, "bucket=missing")
    assert "NoSuchBucket" in text(one(html, "[role=alert]"))


class NoBuckets(FakeBucket):
    async def buckets(self) -> list[dict[str, Any]]:
        return []


def test_no_visible_buckets_says_the_credentials_see_none(
    signed_in: TestClient,
) -> None:
    html = _get(signed_in, NoBuckets([]), "browse")
    assert "credentials" in text(one(html, "#storage-browse [data-empty]"))


PARTIALS = "/partials/overseer/storage"


def test_a_file_downloads_as_an_attachment(signed_in: TestClient) -> None:
    storage_module.set_storage(FakeBucket(OBJECTS))
    response = signed_in.get(
        f"{PARTIALS}/download", params={"bucket": "demo-files", "key": "README.md"}
    )
    assert response.status_code == 200 and response.content == b"# demo"
    assert 'filename="README.md"' in response.headers["content-disposition"]


def test_a_missing_file_is_404(signed_in: TestClient) -> None:
    storage_module.set_storage(FakeBucket(OBJECTS))
    response = signed_in.get(
        f"{PARTIALS}/download", params={"bucket": "demo-files", "key": "gone"}
    )
    assert response.status_code == 404


def test_delete_asks_first(signed_in: TestClient) -> None:
    storage_module.set_storage(FakeBucket(OBJECTS))
    html = signed_in.get(
        f"{PARTIALS}/confirm-delete",
        params={"bucket": "demo-files", "key": "README.md"},
    ).text
    button = one(html, "button[hx-delete]")
    assert "key=README.md" in button.get("hx-delete")


def test_delete_removes_the_file(signed_in: TestClient) -> None:
    """One key or many: the row menu and the checkboxes share one route."""
    bucket = FakeBucket(OBJECTS)
    storage_module.set_storage(bucket)
    response = signed_in.delete(
        f"{PARTIALS}/object", params={"bucket": "demo-files", "key": "README.md"}
    )
    assert response.status_code == 204
    assert ("demo-files", "README.md") not in bucket.files


def test_the_apps_own_bucket_is_read_only(signed_in: TestClient) -> None:
    bucket = FakeBucket(OBJECTS)
    storage_module.set_storage(bucket)
    response = signed_in.delete(
        f"{PARTIALS}/object", params={"bucket": "my-app", "key": "README.md"}
    )
    assert response.status_code == 403
    assert ("my-app", "README.md") in bucket.files


def test_an_upload_lands_in_the_open_folder(signed_in: TestClient) -> None:
    bucket = FakeBucket(OBJECTS)
    storage_module.set_storage(bucket)
    response = signed_in.post(
        f"{PARTIALS}/upload",
        data={"bucket": "demo-files", "prefix": "invoices/"},
        files={"file": ("new.pdf", b"%PDF", "application/pdf")},
    )
    assert response.status_code == 200
    assert bucket.files[("demo-files", "invoices/new.pdf")] == (
        b"%PDF",
        "application/pdf",
    )
    assert "prefix=invoices%2F" in response.headers["HX-Location"]


def test_writable_folders_offer_upload_and_delete(signed_in: TestClient) -> None:
    html = _browse(signed_in, "bucket=demo-files")
    assert select(html, "#storage-upload input[type=file]")
    assert select(html, "#storage-browse [hx-get*='confirm-delete']")


def test_the_apps_bucket_offers_download_only(signed_in: TestClient) -> None:
    html = _browse(signed_in, "bucket=my-app")
    assert not select(html, "#storage-upload")
    assert not select(html, "#storage-browse [hx-get*='confirm-delete']")
    assert select(html, "#storage-browse a[href*='/download']")


def test_bulk_delete_confirms_the_count(signed_in: TestClient) -> None:
    storage_module.set_storage(FakeBucket(OBJECTS))
    html = signed_in.get(
        f"{PARTIALS}/confirm-delete",
        params=[("bucket", "demo-files"), ("key", "a.pdf"), ("key", "b.pdf")],
    ).text
    assert "2 files" in text(one(html, "p"))
    url = one(html, "button[hx-delete]").get("hx-delete")
    assert "key=a.pdf" in url and "key=b.pdf" in url


def test_bulk_delete_removes_every_checked_file(signed_in: TestClient) -> None:
    bucket = FakeBucket(OBJECTS)
    bucket.files[("demo-files", "a.pdf")] = (b"a", None)
    bucket.files[("demo-files", "b.pdf")] = (b"b", None)
    storage_module.set_storage(bucket)
    response = signed_in.delete(
        f"{PARTIALS}/object",
        params=[("bucket", "demo-files"), ("key", "a.pdf"), ("key", "b.pdf")],
    )
    assert response.status_code == 204
    assert ("demo-files", "a.pdf") not in bucket.files
    assert ("demo-files", "b.pdf") not in bucket.files


def test_files_in_writable_buckets_can_be_checked(signed_in: TestClient) -> None:
    boxes = select(
        _browse(signed_in, "bucket=demo-files"), "#storage-browse input[name=key]"
    )
    assert [b.get("value") for b in boxes] == ["README.md"]


def test_the_apps_bucket_has_no_checkboxes(signed_in: TestClient) -> None:
    assert not select(
        _browse(signed_in, "bucket=my-app"), "#storage-browse input[name=key]"
    )


def test_row_actions_sit_behind_an_options_menu(signed_in: TestClient) -> None:
    html = _browse(signed_in, "bucket=demo-files")
    menu = one(html, "#storage-browse details[data-row-menu]")
    assert select(menu, "a[href*='/download']")
    assert select(menu, "[hx-get*='confirm-delete']")


def test_upload_sits_in_the_toolbar_beside_the_path(signed_in: TestClient) -> None:
    html = _browse(signed_in, "bucket=demo-files")
    assert select(html, "#storage-toolbar #storage-crumbs")
    assert select(html, "#storage-toolbar #storage-upload input[type=file]")


def test_a_header_checkbox_selects_every_file(signed_in: TestClient) -> None:
    box = one(
        _browse(signed_in, "bucket=demo-files"),
        "#storage-browse thead input[type=checkbox]",
    )
    assert box.get("name") is None  # never counted as a selected file


def test_the_apps_bucket_has_no_header_checkbox(signed_in: TestClient) -> None:
    assert not select(
        _browse(signed_in, "bucket=my-app"), "#storage-browse thead input"
    )
