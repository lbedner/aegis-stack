"""Stored bytes, addressed by their own content.

The seam every future backend implements. Keys are derived from the
payload's digest rather than from a filename or a path, which is what
makes moving to a bucket a byte copy instead of a migration: the same
key resolves identically wherever the bytes happen to live.
"""

from pathlib import Path

import asyncio

import pytest

from app.core.storage import FilesystemStorage, content_key


class TestContentKey:
    def test_the_key_is_the_digest_and_nothing_else(self) -> None:
        """Same bytes, same key - on any machine, in any backend."""
        assert content_key(b"hello") == content_key(b"hello")
        assert content_key(b"hello") != content_key(b"hello!")

    def test_it_shards_so_no_directory_holds_everything(self) -> None:
        key = content_key(b"hello")
        parts = key.split("/")
        assert parts[0] == "sha256"
        assert len(parts) == 4
        assert parts[3].startswith(parts[1] + parts[2])

    def test_it_carries_no_filename(self) -> None:
        """A key that remembers a path is a key that breaks on the move."""
        assert "." not in content_key(b"%PDF-1.7 fake")


class TestFilesystemStorage:
    def test_it_offers_no_presigned_urls(self, tmp_path: Path) -> None:
        """Files are served through the app; only a bucket can sign a link."""
        store = FilesystemStorage(tmp_path)
        key = asyncio.run(store.put(b"served by the app"))

        assert asyncio.run(store.presigned_url(key, expires_seconds=60)) is None

    @pytest.mark.asyncio
    async def test_put_returns_a_key_that_gets_the_bytes_back(
        self, tmp_path: Path
    ) -> None:
        store = FilesystemStorage(tmp_path)

        key = await store.put(b"scan bytes", content_type="application/pdf")

        assert await store.get(key) == b"scan bytes"

    @pytest.mark.asyncio
    async def test_the_same_bytes_stored_twice_are_one_object(
        self, tmp_path: Path
    ) -> None:
        store = FilesystemStorage(tmp_path)

        first = await store.put(b"same")
        second = await store.put(b"same")

        assert first == second
        assert len([p for p in tmp_path.rglob("*") if p.is_file()]) == 1

    @pytest.mark.asyncio
    async def test_a_key_nobody_stored_is_absent_not_an_error(
        self, tmp_path: Path
    ) -> None:
        store = FilesystemStorage(tmp_path)

        assert await store.exists(content_key(b"never stored")) is False
        assert await store.get(content_key(b"never stored")) is None

    @pytest.mark.asyncio
    async def test_delete_reports_whether_it_removed_anything(
        self, tmp_path: Path
    ) -> None:
        store = FilesystemStorage(tmp_path)
        key = await store.put(b"temporary")

        assert await store.delete(key) is True
        assert await store.delete(key) is False
        assert await store.exists(key) is False

    @pytest.mark.asyncio
    async def test_a_key_from_outside_the_store_cannot_escape_it(
        self, tmp_path: Path
    ) -> None:
        """Keys arrive from a database column; a traversal in one must not
        read the filesystem it was never given."""
        store = FilesystemStorage(tmp_path)

        with pytest.raises(ValueError, match="key"):
            await store.get("../../etc/passwd")

    @pytest.mark.asyncio
    async def test_the_backend_names_itself_for_the_row_that_cites_it(
        self, tmp_path: Path
    ) -> None:
        """Rows record which backend holds the bytes, so a half-migrated
        store still resolves every key."""
        assert FilesystemStorage(tmp_path).backend_name == "filesystem"

    @pytest.mark.asyncio
    async def test_concurrent_writes_of_the_same_bytes_do_not_collide(
        self, tmp_path: Path
    ) -> None:
        """Two callers storing the SAME payload is the common case, not a
        rare one - a shared staging path would let them interleave into a
        corrupt object."""
        store = FilesystemStorage(tmp_path)
        payload = b"x" * 200_000

        keys = await asyncio.gather(*(store.put(payload) for _ in range(12)))

        assert len(set(keys)) == 1
        assert await store.get(keys[0]) == payload
        files = [p for p in tmp_path.rglob("*") if p.is_file()]
        assert len(files) == 1
        assert not any(p.name.endswith(".partial") for p in files)
