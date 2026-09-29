"""The S3 backend speaks the same protocol as the filesystem one.

moto stands in for the bucket, so the suite needs no server. The
property under test is the seam itself: same key in, same bytes out,
absence as an answer, and the bucket created on first use rather than
by hand.
"""

import asyncio

import pytest

from app.components.storage.s3 import S3Storage
from app.core.storage import content_key


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch):
    from moto import mock_aws

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        yield S3Storage(
            bucket="unit-test-bucket",
            endpoint_url=None,
            access_key="testing",
            secret_key="testing",
            region="us-east-1",
            path_style=True,
        )


class _FakeClientError(Exception):
    def __init__(self, code: str) -> None:
        self.response = {"Error": {"Code": code}}


class _StubClient:
    """Just enough of the boto3 client to drive ``_ensure_bucket``."""

    def __init__(self, head_error: str | None) -> None:
        self._head_error = head_error
        self.created: list[dict] = []
        self.exceptions = type("E", (), {"ClientError": _FakeClientError})

    def head_bucket(self, **kwargs: str) -> None:
        if self._head_error:
            raise _FakeClientError(self._head_error)

    def create_bucket(self, **kwargs) -> None:
        self.created.append(kwargs)


class TestEnsureBucket:
    def _store(self, head_error: str | None, *, endpoint: str | None, region: str):
        store = S3Storage.__new__(S3Storage)
        store.bucket, store.endpoint_url, store.region = "b", endpoint, region
        store._client, store._bucket_ready = _StubClient(head_error), False
        return store

    def test_a_missing_bucket_is_created(self) -> None:
        store = self._store("404", endpoint="http://seaweedfs:8333", region="us-east-1")
        store._ensure_bucket()
        assert store._client.created == [{"Bucket": "b"}]

    def test_aws_outside_us_east_1_names_the_region(self) -> None:
        store = self._store("NoSuchBucket", endpoint=None, region="eu-west-1")
        store._ensure_bucket()
        assert store._client.created == [
            {
                "Bucket": "b",
                "CreateBucketConfiguration": {"LocationConstraint": "eu-west-1"},
            }
        ]

    def test_any_other_error_is_not_a_reason_to_create(self) -> None:
        store = self._store("AccessDenied", endpoint=None, region="us-east-1")
        with pytest.raises(_FakeClientError):
            store._ensure_bucket()
        assert store._client.created == []


class TestS3Storage:
    def test_put_then_get_round_trips_under_the_content_key(self, store) -> None:
        key = asyncio.run(store.put(b"renewal request", content_type="text/plain"))

        assert key == content_key(b"renewal request")
        assert asyncio.run(store.get(key)) == b"renewal request"
        assert store.backend_name == "s3"

    def test_the_bucket_is_created_on_first_use(self, store) -> None:
        assert asyncio.run(store.put(b"first bytes")).startswith("sha256/")
        assert asyncio.run(store.exists(content_key(b"first bytes")))

    def test_absence_is_an_answer(self, store) -> None:
        missing = content_key(b"never stored")

        assert asyncio.run(store.get(missing)) is None
        assert asyncio.run(store.exists(missing)) is False
        assert asyncio.run(store.delete(missing)) is False

    def test_delete_removes_and_reports(self, store) -> None:
        key = asyncio.run(store.put(b"short lived"))

        assert asyncio.run(store.delete(key)) is True
        assert asyncio.run(store.exists(key)) is False

    def test_an_empty_store_is_reachable_and_gets_its_bucket(self, store) -> None:
        """Before the first upload there is no bucket; that is not an outage."""
        assert asyncio.run(store.reachable()) is True
        # The bucket itself now answers a HEAD; an object in it still does not.
        store._client.head_bucket(Bucket=store.bucket)
        assert asyncio.run(store.exists(content_key(b"anything"))) is False

    def test_a_presigned_url_names_the_key(self, store) -> None:
        key = asyncio.run(store.put(b"shareable"))

        url = asyncio.run(store.presigned_url(key, expires_seconds=60))

        assert url is not None and key in url and "X-Amz-Signature" in url

    def test_a_bad_key_is_refused_before_any_request(self, store) -> None:
        with pytest.raises(ValueError):
            asyncio.run(store.get("../../etc/passwd"))


class TestListing:
    """The Overseer's Storage page reads the bucket, capped like Redis."""

    def test_every_object_comes_with_its_size_and_time(self, store) -> None:
        for data in (b"a", b"bb", b"ccc"):
            asyncio.run(store.put(data))
        objects, truncated = asyncio.run(store.list_objects(limit=10))
        assert truncated is False
        assert sorted(o["size"] for o in objects) == [1, 2, 3]
        assert {o["key"] for o in objects} == {
            content_key(d) for d in (b"a", b"bb", b"ccc")
        }
        assert all(o["modified"] is not None for o in objects)

    def test_the_listing_stops_at_the_limit_and_says_so(self, store) -> None:
        for data in (b"a", b"bb", b"ccc"):
            asyncio.run(store.put(data))
        objects, truncated = asyncio.run(store.list_objects(limit=2))
        assert len(objects) == 2 and truncated is True

    def test_an_empty_bucket_lists_nothing(self, store) -> None:
        assert asyncio.run(store.list_objects(limit=10)) == ([], False)


class TestBrowsing:
    """Buckets, then one level of a bucket: its folders and its files.

    S3 has no folders; listing with a ``/`` delimiter returns the common
    prefixes every console draws as folders."""

    def _seed(self, store) -> None:
        store._ensure_bucket()
        for key in (
            "invoices/2026-09/a.pdf",
            "invoices/2026-09/b.pdf",
            "invoices/x.pdf",
            "README.md",
        ):
            store._client.put_object(Bucket=store.bucket, Key=key, Body=b"x" * 10)

    def test_buckets_are_listed_by_name(self, store) -> None:
        store._ensure_bucket()
        assert [b["name"] for b in asyncio.run(store.buckets())] == ["unit-test-bucket"]

    def test_the_top_of_a_bucket_shows_folders_and_files(self, store) -> None:
        self._seed(store)
        level = asyncio.run(store.browse(store.bucket, ""))
        assert level["folders"] == ["invoices/"]
        assert [f["key"] for f in level["files"]] == ["README.md"]
        assert level["truncated"] is False

    def test_a_folder_shows_its_own_level(self, store) -> None:
        self._seed(store)
        level = asyncio.run(store.browse(store.bucket, "invoices/"))
        assert level["folders"] == ["invoices/2026-09/"]
        assert [f["key"] for f in level["files"]] == ["invoices/x.pdf"]

    def test_a_level_stops_at_the_limit_and_says_so(self, store) -> None:
        self._seed(store)
        level = asyncio.run(store.browse(store.bucket, "", limit=1))
        assert len(level["folders"]) + len(level["files"]) == 1
        assert level["truncated"] is True


class TestFiles:
    """Download, upload and delete by bucket and key, for the Overseer's
    browser. Unlike ``put``, the caller names the key."""

    def test_an_upload_reads_back_with_its_type(self, store) -> None:
        store._ensure_bucket()
        asyncio.run(store.upload(store.bucket, "docs/a.txt", b"hello", "text/plain"))
        assert asyncio.run(store.fetch(store.bucket, "docs/a.txt")) == (
            b"hello",
            "text/plain",
        )

    def test_a_missing_key_fetches_nothing(self, store) -> None:
        store._ensure_bucket()
        assert asyncio.run(store.fetch(store.bucket, "nope.txt")) is None

    def test_remove_deletes_and_reports(self, store) -> None:
        store._ensure_bucket()
        asyncio.run(store.upload(store.bucket, "a.txt", b"x", None))
        assert asyncio.run(store.remove(store.bucket, "a.txt")) is True
        assert asyncio.run(store.fetch(store.bucket, "a.txt")) is None
        assert asyncio.run(store.remove(store.bucket, "a.txt")) is False


def test_remove_many_deletes_every_key_in_one_call(store) -> None:
    store._ensure_bucket()
    for key in ("a.txt", "b.txt", "c.txt"):
        asyncio.run(store.upload(store.bucket, key, b"x", None))
    asyncio.run(store.remove_many(store.bucket, ["a.txt", "b.txt"]))
    assert asyncio.run(store.fetch(store.bucket, "a.txt")) is None
    assert asyncio.run(store.fetch(store.bucket, "b.txt")) is None
    assert asyncio.run(store.fetch(store.bucket, "c.txt")) is not None
