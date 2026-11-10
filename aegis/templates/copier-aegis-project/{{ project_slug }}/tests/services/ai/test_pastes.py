"""A picture shared in chat keeps what it showed.

Its bytes ride one model call and history replays as text, so the turn
after it the assistant had forgotten the screenshot. The marker now names
each picture by a handle; on the worker it gets a line in the user's
paste index and what it showed is read once and kept there, and
``pasted`` reads it back in any later turn.
"""

import base64
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

import app.core.db
from app.core.discovery import present
from app.core.storage import FilesystemStorage, content_key, set_storage
from app.services.ai.domains.chat import pastes
from app.services.ai.domains.chat.attachments import ChatAttachment, prepare_turn
from app.services.ai.domains.chat.user_memory import memory_user

READABLE = present("app.services.documents") and present("app.components.worker")
pytestmark = pytest.mark.skipif(
    not READABLE, reason="read on the worker, with the documents service's vision"
)
READING = "A transfer screen.\nFrom: Checking"


@pytest.fixture(autouse=True)
def store(
    tmp_path: Path, async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> Iterator[FilesystemStorage]:
    """An object store on disk, and every session the test's own."""

    @asynccontextmanager
    async def session() -> AsyncGenerator[AsyncSession]:
        yield async_db_session

    monkeypatch.setattr(app.core.db, "get_async_session", session)
    monkeypatch.setattr(pastes, "get_async_session", session)
    storage = FilesystemStorage(tmp_path)
    set_storage(storage)
    yield storage
    set_storage(None)


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    """What the turn hands the worker."""
    from app.components.worker import pools

    enqueued: list[tuple[object, ...]] = []

    async def enqueue(name: str, _queue: str, *args: object, **_: object) -> None:
        enqueued.append((name, *args))

    monkeypatch.setattr(pools, "enqueue_task", enqueue)
    return enqueued


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[tuple[bytes, str]]:
    """A model that can see, played by a fake: what it was shown."""
    from app.services.documents import service as documents

    shown: list[tuple[bytes, str]] = []

    async def look(image: bytes, media_type: str, **_: object) -> tuple[str, str]:
        shown.append((image, media_type))
        return READING, "vision-model"

    async def reader() -> object:
        return look

    monkeypatch.setattr(documents, "look", look, raising=False)
    monkeypatch.setattr(documents, "vision_reader", reader)
    return shown


def _png(payload: bytes) -> ChatAttachment:
    return ChatAttachment(
        media_type="image/png",
        data_b64=base64.b64encode(payload).decode(),
        name="shot.png",
    )


async def _shared(user_id: str, data: bytes) -> str:
    """A picture shared in a turn and handed to the worker: its handle."""
    from app.components.worker.tasks.chat_tasks import read_photo_task

    key = content_key(data)
    await prepare_turn("see this", [_png(data)], user_id=user_id)
    await read_photo_task({}, user_id, key, "image/png", "shot.png")
    return pastes.paste_id(key)


class TestTheTurn:
    async def test_names_it_and_where_its_reading_is(
        self, queued: list[tuple[object, ...]]
    ) -> None:
        text, _ = await prepare_turn("see this", [_png(b"a screen")], user_id="u1")

        key = content_key(b"a screen")
        handle = pastes.paste_id(key)
        assert f'shot.png #{handle}, what it showed: pasted("{handle}")' in text
        assert queued == [("read_photo_task", "u1", key, "image/png", "shot.png")]

    async def test_with_no_user_names_no_handle(
        self, queued: list[tuple[object, ...]]
    ) -> None:
        text, _ = await prepare_turn("see this", [_png(b"anon")])

        assert "pasted(" not in text
        assert queued == []


class TestWhatItShowedIsReadBack:
    async def test_pasted_answers_it_once_read(
        self, queued: list[tuple[object, ...]], seen: list[tuple[bytes, str]]
    ) -> None:
        handle = await _shared("u2", b"shot")

        with memory_user("u2"):
            assert await pastes.pasted(handle) == READING
        assert seen == [(b"shot", "image/png")]

    async def test_sharing_it_again_keeps_the_reading_and_reads_nothing(
        self, queued: list[tuple[object, ...]], seen: list[tuple[bytes, str]]
    ) -> None:
        handle = await _shared("u3", b"again")
        assert await _shared("u3", b"again") == handle

        with memory_user("u3"):
            assert await pastes.pasted(handle) == READING
        assert len(seen) == 1

    async def test_without_a_model_that_can_see_it_stays_unread(
        self, queued: list[tuple[object, ...]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services.documents import service as documents

        async def no_reader() -> None:
            return None

        monkeypatch.setattr(documents, "vision_reader", no_reader)
        handle = await _shared("u4", b"unseen")

        with memory_user("u4"):
            assert await pastes.pasted(handle) == pastes.PICTURE_UNREAD

    async def test_an_unknown_handle_says_which_are_on_file(
        self, queued: list[tuple[object, ...]], seen: list[tuple[bytes, str]]
    ) -> None:
        handle = await _shared("u5", b"on file")

        with memory_user("u5"):
            said = await pastes.pasted("nope")
        assert said.endswith(f"On file: {handle}.")
