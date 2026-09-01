"""Durable bytes, addressed by their own content.

The seam between "something needs to keep a file" and wherever files
actually live. One protocol, and backends that implement it: a local
filesystem today, object storage (MinIO in dev, S3 in production) when
that component lands.

Keys are derived from the payload's SHA-256, never from a filename or a
path. That is the whole reason the backend can change later without a
migration: ``sha256/ab/cd/<digest>`` resolves identically on a disk, in
a bucket, and anywhere else, so adopting object storage is a byte copy
with no database change and no key rewriting. Rows that reference stored
bytes keep the key and the backend name; nothing outside a backend ever
builds a path.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
import re
from typing import Protocol, runtime_checkable

DIGEST_ALGORITHM = "sha256"
# A key is exactly what ``content_key`` produces. Keys arrive from
# database columns and API payloads, so they are validated rather than
# trusted: a traversal in one must not reach a file it was never given.
_KEY_PATTERN = re.compile(r"^sha256/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{64}$")


def content_key(data: bytes) -> str:
    """The key these exact bytes are stored under, anywhere.

    Sharded two levels so no single directory holds every object - the
    filesystem backend cares, and object stores are indifferent to it.
    """
    digest = hashlib.sha256(data).hexdigest()
    return f"{DIGEST_ALGORITHM}/{digest[:2]}/{digest[2:4]}/{digest}"


def validate_key(key: str) -> str:
    """The key, or a refusal. Never a path."""
    if not _KEY_PATTERN.match(key):
        raise ValueError(f"not a content-addressed storage key: {key!r}")
    return key


@runtime_checkable
class ObjectStorage(Protocol):
    """What every backend can do, and nothing more.

    Deliberately four methods. Presigned URLs, ranges, and lifecycle
    rules are additions a later backend can offer; they are not what a
    caller needs to store a document and read it back.
    """

    backend_name: str

    async def put(self, data: bytes, *, content_type: str | None = None) -> str:
        """Store the bytes and return the key they now live under."""
        ...

    async def get(self, key: str) -> bytes | None:
        """The bytes, or None when nothing is stored under that key."""
        ...

    async def exists(self, key: str) -> bool: ...

    async def delete(self, key: str) -> bool:
        """True when this call removed an object, False when there was
        nothing to remove - absence is an answer, not an error."""
        ...


class FilesystemStorage:
    """Objects as files under a root directory.

    The backend for stacks without a bucket: tests, a laptop, a single
    container. ``content_type`` is accepted and ignored - it is a fact
    about the object that object stores record and a filesystem has
    nowhere to put; the referencing row keeps it.
    """

    backend_name = "filesystem"

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def _path(self, key: str) -> Path:
        return self._root / validate_key(key)

    async def put(self, data: bytes, *, content_type: str | None = None) -> str:
        key = content_key(data)
        path = self._path(key)
        if path.exists():
            # Same bytes, same key, same object: storing twice costs one.
            return key
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        # Written beside and moved into place, so a reader never sees a
        # half-written object under a key that claims to be complete.
        staged = path.with_suffix(".partial")
        await asyncio.to_thread(staged.write_bytes, data)
        await asyncio.to_thread(staged.replace, path)
        return key

    async def get(self, key: str) -> bytes | None:
        path = self._path(key)
        if not path.exists():
            return None
        return await asyncio.to_thread(path.read_bytes)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).exists)

    async def delete(self, key: str) -> bool:
        path = self._path(key)
        if not path.exists():
            return False
        await asyncio.to_thread(path.unlink)
        return True


_storage: ObjectStorage | None = None


def get_storage() -> ObjectStorage:
    """The configured object store.

    One instance per process, chosen from settings. When the storage
    component lands it decides here between a bucket and the filesystem;
    every caller already speaks the protocol either way.
    """
    global _storage
    if _storage is None:
        from app.core.config import settings

        _storage = FilesystemStorage(settings.STORAGE_ROOT)
    return _storage


def set_storage(storage: ObjectStorage | None) -> None:
    """Point the process at a different store (tests, a backend swap)."""
    global _storage
    _storage = storage
