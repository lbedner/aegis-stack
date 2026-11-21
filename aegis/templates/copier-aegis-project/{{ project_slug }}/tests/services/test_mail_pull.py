"""Mail pulls itself: IMAP with an app password.

The connection is stdlib's ``imaplib`` behind one name, so a fake
mailbox stands in for a provider's here: a dict of UID to raw message. What
the tests hold: each message lands once (the UID watermark, then the
Message-ID), it starts from now and leaves history in the mailbox, it
is only ever read, a refused sign-in is one line on the mailbox row and
never the password, and the pull hands each message to the same ingest
a dropped file takes.
"""

from __future__ import annotations

from collections.abc import Iterator
import imaplib
from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import OpenSession
from app.core.schedule import service_jobs
from app.core.secrets import SecretRejectedError, SecretUncheckedError
from app.services.mail import pull
from app.services.mail.arrivals import arrivals
from app.services.mail.models import MailBatch, MailMailbox, MailMessage
from tests._mbox import message
from tests._secret_settings import secret_settings
from tests._session import rows_of

PASSWORD = "abcd efgh ijkl mnop"
# Most tests pull several times: once to note where the folder ends,
# then for what arrived after.
pytestmark = [
    pytest.mark.queryspy(threshold=5),
    pytest.mark.usefixtures("no_mail_hooks"),
]
BOX = pull.Mailbox("imap.example.com", "sam@example.com", "Receipts", PASSWORD)


class FakeIMAP:
    """``imaplib.IMAP4_SSL``'s surface over a dict of UID -> raw bytes."""

    uidvalidity = 100
    messages: dict[int, bytes] = {}
    down = False
    calls: list[Any] = []

    def __init__(self, host: str, timeout: float | None = None) -> None:
        if FakeIMAP.down:
            raise OSError("no route to host")

    def login(self, user: str, password: str) -> tuple[str, list[bytes]]:
        FakeIMAP.calls.append(("LOGIN", user))
        if password != PASSWORD:
            raise imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials")
        return "OK", [b"Logged in"]

    def select(self, folder: str, readonly: bool = False) -> tuple[str, list[bytes]]:
        FakeIMAP.calls.append(("SELECT", folder, readonly))
        return "OK", [str(len(FakeIMAP.messages)).encode()]

    def response(self, code: str) -> tuple[str, list[bytes | None]]:
        if code == "UIDNEXT":
            return code, [str(max(FakeIMAP.messages, default=0) + 1).encode()]
        return code, [str(FakeIMAP.uidvalidity).encode()]

    @classmethod
    def arrives(cls, uid: int, subject: str) -> None:
        cls.messages[uid] = message(
            subject=subject, message_id=f"<{uid}@example.com>"
        ).as_bytes()

    def uid(self, command: str, *args: Any) -> tuple[str, list[Any]]:
        FakeIMAP.calls.append((command, *args))
        if command == "SEARCH":
            since = int(args[1].split()[1].split(":")[0])
            hits = [u for u in sorted(FakeIMAP.messages) if u >= since]
            # IMAP's ``n:*``: the highest UID always matches, even below n.
            hits = hits or sorted(FakeIMAP.messages)[-1:]
            return "OK", [" ".join(str(u) for u in hits).encode()]
        if command == "FETCH":
            uid = int(args[0])
            raw = FakeIMAP.messages[uid]
            head = f"1 (UID {uid} BODY[] {{{len(raw)}}}".encode()
            return "OK", [(head, raw), b")"]
        raise AssertionError(f"the pull sent {command}")

    def logout(self) -> tuple[str, list[bytes]]:
        FakeIMAP.calls.append(("LOGOUT",))
        return "BYE", []


@pytest.fixture
def imap(monkeypatch: pytest.MonkeyPatch) -> type[FakeIMAP]:
    FakeIMAP.uidvalidity = 100
    FakeIMAP.messages = {}
    FakeIMAP.down = False
    FakeIMAP.calls = []
    monkeypatch.setattr(pull, "IMAP", FakeIMAP)
    return FakeIMAP


async def primed(open_session: OpenSession, imap: type[FakeIMAP]) -> None:
    """The folder seen once, then two messages arrive."""
    await pull.pull_mailbox(open_session, BOX)
    imap.arrives(5, "order")
    imap.arrives(7, "receipt")


class TestEachMessageLandsOnce:
    async def test_the_first_sight_only_notes_where_the_folder_ends(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        imap: type[FakeIMAP],
        dispatched: list[int],
    ) -> None:
        """History stays in the mailbox: a folder of years is not a day
        of model calls."""
        imap.arrives(5, "old order")
        imap.arrives(7, "old receipt")

        assert await pull.pull_mailbox(open_session, BOX) is None

        assert not await rows_of(async_db_session, MailMessage)
        assert not [c for c in imap.calls if c[0] == "FETCH"]
        [box] = await rows_of(async_db_session, MailMailbox)
        assert (box.uidvalidity, box.uid_last) == (100, 7)
        assert box.last_pulled_at is not None

    async def test_new_messages_become_rows_and_the_watermark_moves(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        imap: type[FakeIMAP],
        dispatched: list[int],
    ) -> None:
        await primed(open_session, imap)
        result = await pull.pull_mailbox(open_session, BOX)

        assert result is not None and result.messages_new == 2
        assert {m.subject for m in await rows_of(async_db_session, MailMessage)} == {
            "order",
            "receipt",
        }
        [batch] = await rows_of(async_db_session, MailBatch)
        assert (batch.source, batch.file_name) == ("imap", BOX.label)
        [box] = await rows_of(async_db_session, MailMailbox)
        assert (box.uidvalidity, box.uid_last) == (100, 7)
        assert box.last_pulled_at is not None and box.last_error is None

    async def test_a_second_pull_fetches_nothing_already_seen(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        imap: type[FakeIMAP],
        dispatched: list[int],
    ) -> None:
        await primed(open_session, imap)
        await pull.pull_mailbox(open_session, BOX)
        imap.calls.clear()

        assert await pull.pull_mailbox(open_session, BOX) is None
        assert ("SEARCH", None, "UID 8:*") in imap.calls
        assert not [c for c in imap.calls if c[0] == "FETCH"]
        assert len(await rows_of(async_db_session, MailMessage)) == 2
        assert len(await rows_of(async_db_session, MailBatch)) == 1

    async def test_a_new_uidvalidity_starts_from_now_again(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        imap: type[FakeIMAP],
        dispatched: list[int],
    ) -> None:
        """The server renumbered (a label recreated): UIDs mean
        nothing any more, so the pull notes the new end and reads what
        arrives after it; what was read stays read."""
        await primed(open_session, imap)
        await pull.pull_mailbox(open_session, BOX)
        imap.uidvalidity = 101
        imap.messages = {1: imap.messages[5], 2: imap.messages[7]}

        assert await pull.pull_mailbox(open_session, BOX) is None
        imap.arrives(3, "new")
        result = await pull.pull_mailbox(open_session, BOX)

        assert result is not None and result.messages_new == 1
        assert len(await rows_of(async_db_session, MailMessage)) == 3
        [box] = await rows_of(async_db_session, MailMailbox)
        assert (box.uidvalidity, box.uid_last) == (101, 3)

    async def test_the_rows_say_they_were_pulled_and_from_where(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        imap: type[FakeIMAP],
        dispatched: list[int],
    ) -> None:
        await primed(open_session, imap)
        await pull.pull_mailbox(open_session, BOX)

        [day] = await arrivals(async_db_session, owner_user_id=None)
        assert {m.via for m in day.messages} == {f"pulled from {BOX.label}"}


class TestTheMailboxIsOnlyRead:
    async def test_examine_and_peek_never_a_write(
        self, open_session: OpenSession, imap: type[FakeIMAP], dispatched: list[int]
    ) -> None:
        await primed(open_session, imap)
        await pull.pull_mailbox(open_session, BOX)

        assert ("SELECT", "Receipts", True) in imap.calls
        fetches = [c for c in imap.calls if c[0] == "FETCH"]
        assert fetches and all(c[2] == "(BODY.PEEK[])" for c in fetches)
        assert not [c for c in imap.calls if c[0] in ("STORE", "COPY", "EXPUNGE")]
        assert imap.calls[-1] == ("LOGOUT",)


class TestWhenTheMailboxSaysNo:
    async def test_a_refused_sign_in_is_one_line_on_the_row_never_the_password(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        imap: type[FakeIMAP],
    ) -> None:
        wrong = pull.Mailbox(BOX.host, BOX.user, BOX.folder, "nope nope nope nope")

        assert await pull.pull_mailbox(open_session, wrong) is None

        [box] = await rows_of(async_db_session, MailMailbox)
        assert box.last_error and "refused" in box.last_error
        assert "nope" not in box.last_error and "Invalid" not in box.last_error
        assert box.last_pulled_at is None
        assert not await rows_of(async_db_session, MailBatch)

    async def test_an_unreachable_host_says_so_and_a_good_pull_clears_it(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        imap: type[FakeIMAP],
        dispatched: list[int],
    ) -> None:
        imap.down = True
        await pull.pull_mailbox(open_session, BOX)
        [box] = await rows_of(async_db_session, MailMailbox)
        assert box.last_error and "could not reach" in box.last_error

        imap.down = False
        await pull.pull_mailbox(open_session, BOX)
        await async_db_session.refresh(box)
        assert box.last_error is None and box.last_pulled_at is not None


class TestTheAppPassword:
    @pytest.fixture
    def named(self) -> Iterator[None]:
        with secret_settings(pull.HOST, pull.USER, pull.PASSWORD) as s:
            s.MAIL_IMAP_HOST, s.MAIL_IMAP_USER = BOX.host, BOX.user
            yield

    async def test_a_password_the_server_takes_passes(
        self, imap: type[FakeIMAP], named: None
    ) -> None:
        await pull.verify_password(PASSWORD)
        assert ("LOGOUT",) in imap.calls

    async def test_a_refused_password_is_rejected_at_the_paste(
        self, imap: type[FakeIMAP], named: None
    ) -> None:
        with pytest.raises(SecretRejectedError):
            await pull.verify_password("nope nope nope nope")

    async def test_an_unreachable_server_cannot_say(
        self, imap: type[FakeIMAP], named: None
    ) -> None:
        imap.down = True
        with pytest.raises(SecretUncheckedError):
            await pull.verify_password(PASSWORD)

    async def test_host_and_user_come_first(self, imap: type[FakeIMAP]) -> None:
        with secret_settings(pull.HOST, pull.USER, pull.PASSWORD):
            with pytest.raises(SecretUncheckedError):
                await pull.verify_password(PASSWORD)
        assert not imap.calls


class TestTheJob:
    def test_it_is_scheduled_and_not_held_to_the_server(self) -> None:
        """A dev stack pulls too: a second reader of a read-only mailbox
        costs nobody anything."""
        job = next(j for j in service_jobs() if j.id == "mail_pull")
        assert job.func is pull.mail_pull_job and not job.server_only

    async def test_without_a_mailbox_it_does_nothing(
        self, imap: type[FakeIMAP], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _none() -> pull.Mailbox | None:
            return None

        monkeypatch.setattr(pull, "configured", _none)
        await pull.mail_pull_job()
        assert not imap.calls

    async def test_the_mailbox_is_read_from_the_secrets(self) -> None:
        with secret_settings(pull.HOST, pull.USER, pull.FOLDER, pull.PASSWORD) as s:
            s.MAIL_IMAP_HOST, s.MAIL_IMAP_USER = BOX.host, BOX.user
            s.MAIL_IMAP_PASSWORD = PASSWORD
            box = await pull.configured()
        assert box == pull.Mailbox(BOX.host, BOX.user, "INBOX", PASSWORD)
