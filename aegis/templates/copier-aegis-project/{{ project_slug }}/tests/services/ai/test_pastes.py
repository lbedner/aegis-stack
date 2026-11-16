"""What was pasted or shared in chat is kept once and read on demand.

A wall of pasted text is lifted out of the message: the bytes go to the
object store and a one-line marker stands where it was, so history replays
a line instead of the page. An attached PDF is read by the documents
service and stands the same way. A picture's bytes ride one model call; on
the worker it gets a line in the user's paste index and what it showed is
read once and kept there. ``pasted`` reads any of them back in a later
turn.
"""

import base64
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
import time
from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.backend.api.ai import chat as chat_api
from app.components.backend.api.ai.service import ai_service, lifted_turn
from app.core.chat_transcript import readable
import app.core.db
from app.core.discovery import present
from app.core.storage import FilesystemStorage, content_key, set_storage
from app.services.ai.domains.chat import pastes
from app.services.ai.domains.chat.attachments import (
    PASTE_THRESHOLD,
    ChatAttachment,
    prepare_turn,
)
from app.services.ai.domains.chat.user_memory import memory_user

DOCUMENTS = present("app.services.documents")
READABLE = DOCUMENTS and present("app.components.worker")
pictures = pytest.mark.skipif(
    not READABLE, reason="read on the worker, with the documents service's vision"
)
READING = "A transfer screen.\nFrom: Checking"
# A page someone pasted: past the threshold, its first line its name.
PAGE = "Your Orders\n" + "\n".join(f"Order {n}: one item" for n in range(200))


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
def db(async_db_session: AsyncSession) -> AsyncSession:
    """The session a caller hands the paste index: the test's own."""
    return async_db_session


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


async def _turn(
    message: str,
    attachments: list[ChatAttachment] | None,
    user_id: str = "",
    owner_user_id: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """A turn as its way in runs it: lifted first, in a session of its own
    (``lifted_turn``), then the turn, which opens none."""
    lifted = await lifted_turn(message, attachments, user_id, owner_user_id)
    return await prepare_turn(message, attachments, user_id, lifted=lifted)


async def _shared(user_id: str, data: bytes) -> str:
    """A picture shared in a turn and handed to the worker: its handle."""
    from app.components.worker.tasks.chat_tasks import read_photo_task

    key = content_key(data)
    await prepare_turn("see this", [_png(data)], user_id=user_id)
    await read_photo_task({}, user_id, key, "image/png", "shot.png")
    return pastes.paste_id(key)


@pictures
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


@pictures
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


class TestAMarkerWithNoEnd:
    def test_it_is_read_in_linear_time(self) -> None:
        """A message is whoever typed it: an unclosed marker over a long run
        of hex digits backtracked quadratically (CodeQL py/polynomial-redos)."""
        text = "[pasted text #" + "0" * 100_000
        started = time.perf_counter()
        assert readable(text) == text
        assert time.perf_counter() - started < 0.5

    def test_many_of_them_are_read_in_linear_time(self) -> None:
        """Each unclosed marker's tail stops at the next one's bracket, so
        a message of them is not rescanned from every start."""
        text = "[pasted text #0 x" * 20_000
        started = time.perf_counter()
        assert readable(text) == text
        assert time.perf_counter() - started < 0.5


class TestAWallOfText:
    async def test_a_question_is_left_alone(self, db: AsyncSession) -> None:
        assert await pastes.lift_walls(db, "w1", "what did I spend on groceries?") == (
            "what did I spend on groceries?",
            [],
        )

    async def test_the_wall_is_lifted_and_the_sentence_around_it_stays(
        self, db: AsyncSession
    ) -> None:
        text, (paste,) = await pastes.lift_walls(
            db, "w2", f"here is the page\n\n{PAGE}\n\nwhat is late?"
        )

        assert text == f"here is the page\n\n{paste.marker}\n\nwhat is late?"
        with memory_user("w2"):
            assert await pastes.pasted(paste.id) == PAGE

    async def test_a_long_message_of_short_blocks_keeps_them(
        self, db: AsyncSession
    ) -> None:
        typed = "\n\n".join(["a paragraph someone typed"] * 120)
        assert len(typed) > PASTE_THRESHOLD
        assert await pastes.lift_walls(db, "w3", typed) == (typed, [])

    def test_its_name_skips_navigation_furniture(self) -> None:
        assert pastes.title_of("All\nCart\nYour Orders\nmore") == "Your Orders"
        assert pastes.title_of("a\nb") == "pasted text"


class TestAPasteIsKept:
    async def test_its_marker_says_what_it_is_and_how_to_read_it(
        self, db: AsyncSession
    ) -> None:
        paste = await pastes.store_paste(db, "p1", PAGE)

        assert paste.marker == (
            f"[pasted text #{paste.id}: Your Orders - {len(PAGE):,} characters."
            f' Read it with pasted("{paste.id}")]'
        )
        # The reader is shown a chip instead.
        assert readable(f"see {paste.marker}") == "see"

    async def test_the_text_comes_back_exactly(self, db: AsyncSession) -> None:
        paste = await pastes.store_paste(db, "p2", PAGE)

        with memory_user("p2"):
            assert await pastes.pasted(paste.id) == PAGE

    async def test_the_same_page_twice_is_one_line(self, db: AsyncSession) -> None:
        first = await pastes.store_paste(db, "p3", PAGE)
        assert (await pastes.store_paste(db, "p3", PAGE)).id == first.id

        assert [p.id for p in await pastes.pastes_of(db, "p3")] == [first.id]

    async def test_another_users_paste_is_not_theirs_to_read(
        self, db: AsyncSession
    ) -> None:
        paste = await pastes.store_paste(db, "p4", PAGE)

        found = await pastes.read_paste(
            db, "someone-else", paste.id, owner_user_id=None
        )
        assert found is None

    async def test_an_unknown_handle_names_nothing_on_file(
        self, db: AsyncSession
    ) -> None:
        paste = await pastes.store_paste(db, "p5", PAGE)

        with memory_user("p5"):
            said = await pastes.pasted("nope")
        assert said.startswith("No paste 'nope' on file.")
        assert paste.id not in said

    async def test_a_line_pushed_out_takes_its_bytes_with_it(
        self,
        db: AsyncSession,
        store: FilesystemStorage,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(pastes, "MAX_PASTES_PER_USER", 1)
        first = await pastes.store_paste(db, "p6", PAGE)
        assert first.key is not None
        await pastes.store_paste(db, "p6", f"{PAGE}\nOrder 200: one item")

        assert not await store.exists(first.key)

    async def test_bytes_another_line_still_names_stay(
        self,
        db: AsyncSession,
        store: FilesystemStorage,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(pastes, "MAX_PASTES_PER_USER", 1)
        first = await pastes.store_paste(db, "p7", PAGE)
        assert first.key is not None
        await pastes.store_paste(db, "p8", PAGE)  # the same page, someone else's
        await pastes.store_paste(db, "p7", f"{PAGE}\nOrder 200: one item")

        assert await store.exists(first.key)


class TestTheTurnLiftsIt:
    async def test_the_stored_message_carries_the_marker_not_the_page(self) -> None:
        text, meta = await _turn(f"what is late?\n\n{PAGE}", None, "t1")

        (paste,) = meta["pastes"]
        assert PAGE not in text
        assert text == f"what is late?\n\n{pastes.Paste(**paste).marker}"
        assert paste["title"] == "Your Orders"

    async def test_a_paste_the_composer_lifted_is_named_on_the_message(
        self, db: AsyncSession
    ) -> None:
        staged = await pastes.store_paste(db, "t2", PAGE)

        text, meta = await _turn(f"look {staged.marker}", None, "t2")

        assert text == f"look {staged.marker}"
        assert [p["id"] for p in meta["pastes"]] == [staged.id]

    async def test_without_a_user_nothing_is_lifted(self) -> None:
        assert await _turn(PAGE, None) == (PAGE, {})

    async def test_the_turn_itself_opens_no_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The lift is its way in's, before the turn: a session the turn
        opened would be held across the streamed answer. Not lifted, the
        page goes as it came."""

        def no_session() -> None:
            raise AssertionError("the turn opened a session")

        monkeypatch.setattr(app.core.db, "get_async_session", no_session)
        monkeypatch.setattr(pastes, "get_async_session", no_session)

        text, meta = await prepare_turn(f"what is late?\n\n{PAGE}", None, "t3")

        assert (text, meta) == (f"what is late?\n\n{PAGE}", {})

    async def test_a_way_in_lifts_the_page_before_the_turn(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The API's stream hands the turn its paste already lifted."""
        asked: list[dict[str, Any]] = []

        def stream_chat(**kwargs: Any) -> Any:
            asked.append(kwargs)
            return iter(())

        monkeypatch.setattr(ai_service, "stream_chat", stream_chat)
        request = chat_api.ChatRequest(message=f"what is late?\n\n{PAGE}", user_id="t4")

        await chat_api.chat_stream(request, owner_user_id=None)

        (lifted,) = [a["lifted"] for a in asked]
        (paste,) = lifted.pastes
        assert lifted.text == f"what is late?\n\n{pastes.Paste(**paste).marker}"


@pytest.mark.skipif(not DOCUMENTS, reason="a PDF is read by the documents service")
class TestAnAttachedPdf:
    @pytest.fixture(autouse=True)
    def reader(
        self, async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Extraction in the test's session, with no model to see scans,
        run as the job a stack without a worker runs."""
        from app.services.documents.domains.extraction import dispatch, jobs

        @asynccontextmanager
        async def session() -> AsyncGenerator[AsyncSession]:
            yield async_db_session

        async def no_vision() -> None:
            return None

        monkeypatch.setattr(jobs, "get_async_session", session)
        monkeypatch.setattr(jobs, "vision_reader", no_vision)
        monkeypatch.setattr(
            dispatch, "start_extraction", dispatch.start_extraction_in_process
        )

    @staticmethod
    def _pdf(texts: list[str]) -> ChatAttachment:
        from tests._pdf import pdf_bytes

        return ChatAttachment(
            media_type="application/pdf",
            data_b64=base64.b64encode(pdf_bytes(texts)).decode(),
            name="statement.pdf",
        )

    async def test_it_is_read_and_stands_as_a_marker(self) -> None:
        pdf = self._pdf(["Due June 1"])
        text, meta = await _turn("what is due?", [pdf], "d1")

        (paste,) = meta["pastes"]
        assert text == f"what is due?\n\n{pastes.Paste(**paste).marker}"
        # Its pages, not its bytes: nothing rides as an attachment.
        assert "attachments" not in meta
        with memory_user("d1"):
            assert await pastes.pasted(paste["id"]) == "--- page 1 ---\nDue June 1"

    async def test_its_pages_are_read_as_a_job_not_in_the_turn(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Where there is a worker the job runs there (``start_extraction``):
        the webserver renders no page."""
        from app.services.documents.domains.extraction import dispatch

        started: list[int] = []

        async def start(document_id: int, **kwargs: Any) -> str:
            started.append(document_id)
            return await dispatch.start_extraction_in_process(document_id, **kwargs)

        monkeypatch.setattr(dispatch, "start_extraction", start)
        _, meta = await _turn("what is due?", [self._pdf(["Due June 1"])], "d4")

        (paste,) = meta["pastes"]
        assert started == [paste["document_id"]]

    @pytest.mark.queryspy(allow_n_plus_one=True)  # read as three owners
    async def test_another_owners_document_is_not_read(self, db: AsyncSession) -> None:
        """The index is keyed by the chat's user name; the pages are the
        document's owner's, read in the turn's owner's scope."""
        pdf = self._pdf(["Due June 1"])
        _, meta = await _turn("what is due?", [pdf], "d3", owner_user_id=5)

        (paste,) = meta["pastes"]
        assert await pastes.read_paste(db, "d3", paste["id"], owner_user_id=6) is None
        with memory_user("d3", owner_user_id=6):
            assert "Due June 1" not in await pastes.pasted(paste["id"])
        with memory_user("d3", owner_user_id=5):
            assert "Due June 1" in await pastes.pasted(paste["id"])

    async def test_a_scan_with_nothing_to_read_says_so(self) -> None:
        _, meta = await _turn("and this?", [self._pdf([""])], "d2")

        (paste,) = meta["pastes"]
        with memory_user("d2"):
            said = await pastes.pasted(paste["id"])
        assert said.startswith("--- page 1 ---\n[page 1 could not be read")
