"""Attachments outlive the turn that carried them.

Bytes used to ride one model call and vanish: a reopened conversation
showed a marker for a screenshot nobody could look at again, and replay
could only re-send what session memory still held. With an object store
the image is kept once and the message remembers where.
"""

import pytest

from app.core.storage import FilesystemStorage, content_key, set_storage
from app.services.ai.domains.chat.attachments import (
    ChatAttachment,
    attachment_metadata,
    persist_attachments,
)


@pytest.fixture
def store(tmp_path):
    storage = FilesystemStorage(tmp_path)
    set_storage(storage)
    yield storage
    set_storage(None)


def _png(payload: bytes = b"fake png bytes") -> ChatAttachment:
    import base64

    return ChatAttachment(
        media_type="image/png",
        data_b64=base64.b64encode(payload).decode(),
        name="receipt.png",
    )


class TestPersistAttachments:
    @pytest.mark.asyncio
    async def test_the_bytes_are_stored_and_the_descriptor_points_at_them(
        self, store
    ) -> None:
        stored = await persist_attachments([_png()])

        assert len(stored) == 1
        assert stored[0]["key"] == content_key(b"fake png bytes")
        assert stored[0]["media_type"] == "image/png"
        assert stored[0]["name"] == "receipt.png"
        assert await store.get(stored[0]["key"]) == b"fake png bytes"

    @pytest.mark.asyncio
    async def test_the_same_image_twice_is_stored_once(self, store) -> None:
        """Re-attaching a screenshot already in the store costs nothing -
        that is what content addressing buys."""
        first = await persist_attachments([_png()])
        second = await persist_attachments([_png()])

        assert first[0]["key"] == second[0]["key"]

    @pytest.mark.asyncio
    async def test_no_attachments_touches_no_storage(self, store) -> None:
        assert await persist_attachments(None) == []
        assert await persist_attachments([]) == []

    @pytest.mark.asyncio
    async def test_a_storage_failure_never_costs_the_user_their_message(
        self, store, monkeypatch
    ) -> None:
        """The turn is the point; keeping the picture is a bonus. A store
        that is full or unreachable must not swallow the question."""

        async def boom(*_args, **_kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(store, "put", boom)

        assert await persist_attachments([_png()]) == []


class TestAttachmentMetadata:
    def test_descriptors_ride_the_message_metadata(self) -> None:
        descriptors = [{"key": "sha256/ab/cd/ef", "media_type": "image/png"}]

        assert attachment_metadata(descriptors) == {"attachments": descriptors}

    def test_nothing_attached_means_no_metadata_at_all(self) -> None:
        """An empty dict, not a key holding an empty list: a message that
        carried no image should read as one."""
        assert attachment_metadata([]) == {}
