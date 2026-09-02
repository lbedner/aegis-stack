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

    def test_a_presigned_url_names_the_key(self, store) -> None:
        key = asyncio.run(store.put(b"shareable"))

        url = asyncio.run(store.presigned_url(key, expires_seconds=60))

        assert url is not None and key in url and "X-Amz-Signature" in url

    def test_a_bad_key_is_refused_before_any_request(self, store) -> None:
        with pytest.raises(ValueError):
            asyncio.run(store.get("../../etc/passwd"))
