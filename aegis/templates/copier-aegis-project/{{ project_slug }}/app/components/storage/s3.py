"""The bucket-backed implementation of ``ObjectStorage``.

Vendor-blind: an endpoint, a bucket, credentials, a region. The same code
talks to AWS, to the SeaweedFS container in the dev stack, or to a Garage
box in a closet. Keys are the content-addressed ones every backend
shares, so a stack moves here from the filesystem by copying objects in.

boto3 is synchronous; every call runs in a worker thread so the event
loop keeps serving while a 9 MB scan uploads.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.storage import content_key, validate_key


class S3Storage:
    """Objects in one bucket, created on first use if it is missing."""

    backend_name = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None,
        access_key: str | None,
        secret_key: str | None,
        region: str,
        path_style: bool = True,
    ) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.endpoint_url = endpoint_url
        self.region = region
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(
                # SigV4 everywhere: what AWS requires today and what the
                # self-hosted stores implement.
                signature_version="s3v4",
                s3={"addressing_style": "path" if path_style else "virtual"},
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
        self._bucket_ready = False

    @classmethod
    def from_settings(cls, settings: Any) -> S3Storage:
        return cls(
            bucket=settings.S3_BUCKET,
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            access_key=settings.S3_ACCESS_KEY or None,
            secret_key=settings.S3_SECRET_KEY or None,
            region=settings.S3_REGION,
            path_style=settings.S3_PATH_STYLE,
        )

    # -- the protocol -----------------------------------------------------

    async def put(self, data: bytes, *, content_type: str | None = None) -> str:
        key = content_key(data)
        await asyncio.to_thread(self._put, key, data, content_type)
        return key

    async def get(self, key: str) -> bytes | None:
        return await asyncio.to_thread(self._get, validate_key(key))

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._exists, validate_key(key))

    async def delete(self, key: str) -> bool:
        return await asyncio.to_thread(self._delete, validate_key(key))

    async def presigned_url(
        self, key: str, *, expires_seconds: int = 600
    ) -> str | None:
        """A time-limited link straight to the object, no app in the middle."""
        validate_key(key)
        return await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )

    async def list_objects(self, limit: int) -> tuple[list[dict[str, Any]], bool]:
        """Up to ``limit`` objects (key, size, last modified), and whether
        the bucket holds more. Paged, never unbounded: a big bucket is
        sampled, the same as the Redis keyspace."""
        return await asyncio.to_thread(self._list, limit)

    async def buckets(self) -> list[dict[str, Any]]:
        """Every bucket these credentials can see, by name."""
        return await asyncio.to_thread(self._buckets)

    async def browse(
        self, bucket: str, prefix: str, limit: int = 1000
    ) -> dict[str, Any]:
        """One level of ``bucket`` under ``prefix``: its folders (the common
        prefixes a ``/`` delimiter returns; S3 has no real folders) and its
        files, capped at ``limit`` entries."""
        return await asyncio.to_thread(self._browse, bucket, prefix, limit)

    # -- by bucket and key, for the Overseer's browser ---------------------
    # Unlike ``put``, the caller names the key and the bucket.

    async def fetch(self, bucket: str, key: str) -> tuple[bytes, str | None] | None:
        """An object's bytes and content type, or None if there is none."""
        return await asyncio.to_thread(self._fetch, bucket, key)

    async def upload(
        self, bucket: str, key: str, data: bytes, content_type: str | None
    ) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        await asyncio.to_thread(
            self._client.put_object, Bucket=bucket, Key=key, Body=data, **extra
        )

    async def remove_many(self, bucket: str, keys: list[str]) -> None:
        """Delete every key, a thousand per request (the S3 limit)."""
        for start in range(0, len(keys), 1000):
            batch = [{"Key": key} for key in keys[start : start + 1000]]
            await asyncio.to_thread(
                self._client.delete_objects,
                Bucket=bucket,
                Delete={"Objects": batch, "Quiet": True},
            )

    async def remove(self, bucket: str, key: str) -> bool:
        """Delete an object; False if it was not there."""
        return await asyncio.to_thread(self._remove, bucket, key)

    async def reachable(self) -> bool:
        """Can we reach the bucket? A bucket that does not exist yet is
        created here, the same as on first put: an empty store is healthy,
        not unreachable."""
        try:
            await asyncio.to_thread(self._ensure_bucket)
        except Exception:  # noqa: BLE001 - any failure is "not reachable"
            return False
        return True

    # -- blocking halves, run in threads ----------------------------------

    def _ensure_bucket(self) -> None:
        """Create the bucket only when it is genuinely absent.

        A 404 means missing; anything else (AccessDenied, a bad endpoint)
        is a real error that creating a bucket would only paper over.
        """
        if self._bucket_ready:
            return
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except self._client.exceptions.ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code not in ("404", "NoSuchBucket", "NotFound"):
                raise
            self._client.create_bucket(Bucket=self.bucket, **self._create_args())
        self._bucket_ready = True

    def _create_args(self) -> dict[str, Any]:
        # AWS insists on a LocationConstraint outside us-east-1 and rejects
        # one inside it; self-hosted stores ignore the field either way.
        if self.endpoint_url is None and self.region != "us-east-1":
            return {"CreateBucketConfiguration": {"LocationConstraint": self.region}}
        return {}

    def _list(self, limit: int) -> tuple[list[dict[str, Any]], bool]:
        self._ensure_bucket()
        found: list[dict[str, Any]] = []
        pages = self._client.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, PaginationConfig={"PageSize": min(limit, 1000)}
        )
        for page in pages:
            for item in page.get("Contents", []):
                if len(found) == limit:
                    return found, True
                found.append(
                    {
                        "key": item["Key"],
                        "size": item["Size"],
                        "modified": item.get("LastModified"),
                    }
                )
        return found, False

    def _buckets(self) -> list[dict[str, Any]]:
        listed = self._client.list_buckets().get("Buckets", [])
        return sorted(
            ({"name": b["Name"], "created": b.get("CreationDate")} for b in listed),
            key=lambda b: b["name"],
        )

    def _browse(self, bucket: str, prefix: str, limit: int) -> dict[str, Any]:
        folders: list[str] = []
        files: list[dict[str, Any]] = []
        pages = self._client.get_paginator("list_objects_v2").paginate(
            Bucket=bucket,
            Prefix=prefix,
            Delimiter="/",
            PaginationConfig={"PageSize": min(limit, 1000)},
        )
        for page in pages:
            entries = [("folder", p["Prefix"]) for p in page.get("CommonPrefixes", [])]
            entries += [("file", item) for item in page.get("Contents", [])]
            for kind, entry in entries:
                if len(folders) + len(files) == limit:
                    return {"folders": folders, "files": files, "truncated": True}
                if kind == "folder":
                    folders.append(entry)
                elif entry["Key"] != prefix:
                    files.append(
                        {
                            "key": entry["Key"],
                            "size": entry["Size"],
                            "modified": entry.get("LastModified"),
                        }
                    )
        return {"folders": folders, "files": files, "truncated": False}

    def _missing(self, exc: Exception) -> bool:
        code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
        return code in ("404", "NoSuchKey", "NotFound")

    def _fetch(self, bucket: str, key: str) -> tuple[bytes, str | None] | None:
        # ponytail: reads the whole object into memory; stream it if the
        # browser ever serves files bigger than a few hundred MB.
        try:
            reply = self._client.get_object(Bucket=bucket, Key=key)
        except self._client.exceptions.ClientError as exc:
            if self._missing(exc):
                return None
            raise
        return reply["Body"].read(), reply.get("ContentType")

    def _remove(self, bucket: str, key: str) -> bool:
        try:
            self._client.head_object(Bucket=bucket, Key=key)
        except self._client.exceptions.ClientError as exc:
            if self._missing(exc):
                return False
            raise
        self._client.delete_object(Bucket=bucket, Key=key)
        return True

    def _put(self, key: str, data: bytes, content_type: str | None) -> None:
        self._ensure_bucket()
        if self._exists(key):
            # Same bytes, same key, same object: storing twice costs one.
            return
        extra = {"ContentType": content_type} if content_type else {}
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)

    def _get(self, key: str) -> bytes | None:
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
        except self._client.exceptions.NoSuchKey:
            return None
        except self._client.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchBucket", "404"):
                return None
            raise
        return response["Body"].read()

    def _exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
        except self._client.exceptions.ClientError:
            return False
        return True

    def _delete(self, key: str) -> bool:
        # S3 deletes are idempotent and silent; ask first so absence stays
        # an answer, the same contract the filesystem backend keeps.
        if not self._exists(key):
            return False
        self._client.delete_object(Bucket=self.bucket, Key=key)
        return True
