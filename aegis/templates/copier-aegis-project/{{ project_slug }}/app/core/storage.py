"""Durable bytes, addressed by their own content.

The seam between "something needs to keep a file" and wherever files
actually live. One protocol, and backends that implement it: a local
filesystem here, a bucket in ``app.components.storage.s3`` when the
storage component is selected.

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
import os
from pathlib import Path
import re
import tempfile
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

    Deliberately small. Ranges and lifecycle rules are additions a later
    backend can offer; they are not what a caller needs to store a
    document and read it back. ``presigned_url`` is the one extra: a
    bucket can hand out a time-limited link, a filesystem cannot.
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

    async def presigned_url(self, key: str, *, expires_seconds: int = 600) -> str | None:
        """A time-limited link straight to the object, or None when this
        backend can only serve through the app."""
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

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        """Write, then move into place under the real key.

        Staged under a name unique to this write rather than a fixed
        ``.partial``: two callers storing the SAME bytes is the common
        case, not a rare one, and a shared staging path lets them
        interleave into a corrupt object. The move is atomic, so a
        reader either sees a complete object or no object.
        """
        if path.exists():
            # Same bytes, same key, same object: storing twice costs one.
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, staged = tempfile.mkstemp(dir=path.parent, suffix=".partial")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(staged, path)
        except BaseException:
            Path(staged).unlink(missing_ok=True)
            raise

    async def put(self, data: bytes, *, content_type: str | None = None) -> str:
        key = content_key(data)
        # Every filesystem touch happens in the thread, including the
        # stat: a stat on a slow or network disk blocks the event loop
        # exactly as a read does.
        await asyncio.to_thread(self._write, self._path(key), data)
        return key

    @staticmethod
    def _read(path: Path) -> bytes | None:
        try:
            return path.read_bytes()
        except FileNotFoundError:
            # Absence is an answer, and asking first would be a second
            # syscall that another process can invalidate anyway.
            return None

    async def get(self, key: str) -> bytes | None:
        return await asyncio.to_thread(self._read, self._path(key))

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).exists)

    @staticmethod
    def _unlink(path: Path) -> bool:
        try:
            path.unlink()
        except FileNotFoundError:
            # Checking first then unlinking is a race: another worker can
            # remove it in between, turning "absent" into a crash.
            return False
        return True

    async def delete(self, key: str) -> bool:
        return await asyncio.to_thread(self._unlink, self._path(key))

    async def presigned_url(self, key: str, *, expires_seconds: int = 600) -> str | None:
        validate_key(key)
        return None


_storage: ObjectStorage | None = None


def get_storage() -> ObjectStorage:
    """The configured object store.

    One instance per process, chosen from settings: a bucket when the
    storage component set ``STORAGE_BACKEND`` to ``s3``, the filesystem
    otherwise. Every caller speaks the protocol either way.
    """
    global _storage
    if _storage is None:
        from app.core.config import settings

        if getattr(settings, "STORAGE_BACKEND", "filesystem") == "s3":
            from app.components.storage.s3 import S3Storage

            _storage = S3Storage.from_settings(settings)
        else:
            _storage = FilesystemStorage(settings.STORAGE_ROOT)
    return _storage


def set_storage(storage: ObjectStorage | None) -> None:
    """Point the process at a different store (tests, a backend swap)."""
    global _storage
    _storage = storage
