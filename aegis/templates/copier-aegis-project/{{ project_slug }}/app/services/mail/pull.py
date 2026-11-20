"""Mail pulls itself: IMAP with an app password.

A provider's own mail API means an OAuth client, a consent screen and
expiring tokens. IMAP needs none of that: a host, an address, a folder
(a provider's label is one), and an app password - a secret in the
encrypted store like any other, verified by one sign-in at the paste.
Every provider speaks it.

Read-only, always: the folder is EXAMINEd, bodies are PEEKed, nothing
is flagged, moved or deleted. From now on, not from the beginning: the
first sight of a folder (or a renumbered one) only notes where it ends,
and each pull after asks for the UIDs above the last one seen (UIDs
climb within one UIDVALIDITY). History stays in the mailbox; reading
it on request is its own stream. Every message goes to the same ingest
a dropped ``.eml`` takes, so nothing downstream knows the difference.

The password reaches ``imaplib`` and nowhere else. What a failure says
is this module's own words: a server's text is never repeated.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime
import hashlib
import imaplib
from typing import Any

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import secrets
from app.core.db import OpenSession, get_async_session
from app.core.figures import FIGURES
from app.core.log import logger
from app.core.secrets import Secret, SecretRejectedError, SecretUncheckedError
from app.services.mail import parse, queries
from app.services.mail.ingest import MailImportResult, ingest_messages
from app.services.mail.models import SOURCE_IMAP

HOST = "MAIL_IMAP_HOST"
USER = "MAIL_IMAP_USER"
FOLDER = "MAIL_IMAP_FOLDER"
PASSWORD = "MAIL_IMAP_PASSWORD"
DEFAULT_FOLDER = "INBOX"
TIMEOUT = 30.0
# Messages per pull; the rest come next time. ponytail: one FETCH per
# message, so a first pull of a full label takes a few rounds; a
# batched FETCH when that is measured slow.
PULL_BATCH = 200
# One name for the connection, so a test can stand a mailbox in.
IMAP = imaplib.IMAP4_SSL


class MailboxError(Exception):
    """A pull that could not happen, in words safe to show."""


class MailboxRefusedError(MailboxError):
    """The server would not take the sign-in."""


class MailboxUnreachableError(MailboxError):
    """The server could not be reached, or the folder is not there."""


@dataclass(frozen=True)
class Mailbox:
    host: str
    user: str
    folder: str
    password: str

    @property
    def key(self) -> str:
        return f"{self.host}/{self.user}/{self.folder}"

    @property
    def label(self) -> str:
        """How a person names it: the address and the folder."""
        return f"{self.user} / {self.folder}"


class MailboxStatus(BaseModel):
    """For the Mail page: which mailbox is pulled, when it last was, and
    the one line if the last pull failed."""

    model_config = FIGURES

    label: str
    pulled_at: datetime | None
    error: str | None


@dataclass(frozen=True)
class Fetched:
    uidvalidity: int
    uid_last: int
    messages: list[bytes]


async def configured() -> Mailbox | None:
    """The mailbox the secrets name, or nothing until all three are set."""
    found = await secrets.get_many(HOST, USER, FOLDER, PASSWORD)
    host, user, password = found.get(HOST), found.get(USER), found.get(PASSWORD)
    if not (host and user and password):
        return None
    return Mailbox(host, user, found.get(FOLDER) or DEFAULT_FOLDER, password)


@contextmanager
def _signed_in(box: Mailbox) -> Iterator[Any]:
    """A connection signed in as the mailbox, logged out on the way out."""
    try:
        conn = IMAP(box.host, timeout=TIMEOUT)
    except (OSError, imaplib.IMAP4.error):
        raise MailboxUnreachableError(f"could not reach {box.host}") from None
    try:
        try:
            conn.login(box.user, box.password)
        except imaplib.IMAP4.error:
            raise MailboxRefusedError(
                f"{box.host} refused the sign-in for {box.user}"
            ) from None
        yield conn
    finally:
        with suppress(Exception):
            conn.logout()


def fetch_new(
    box: Mailbox, *, uidvalidity: int | None, uid_last: int, cap: int
) -> Fetched:
    """Every message above the watermark, oldest first, at most ``cap``
    (the rest come next pull). A folder seen for the first time, or
    renumbered, is only marked at its end. Blocking: run it in a thread."""
    with _signed_in(box) as conn:
        status, _ = conn.select(box.folder, readonly=True)
        if status != "OK":
            raise MailboxUnreachableError(f"no folder {box.folder!r} in {box.user}")
        validity = int((conn.response("UIDVALIDITY")[1] or [b"0"])[0] or 0)
        if validity != uidvalidity:
            uidnext = int((conn.response("UIDNEXT")[1] or [b"1"])[0] or 1)
            return Fetched(validity, uidnext - 1, [])
        since = uid_last + 1
        _, found = conn.uid("SEARCH", None, f"UID {since}:*")
        # ``n:*`` always matches the highest UID, even below n: filter.
        uids = sorted(n for n in map(int, (found[0] or b"").split()) if n >= since)
        uids = uids[:cap]
        messages = []
        for uid in uids:
            _, parts = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
            if raw:
                messages.append(bytes(raw))
        return Fetched(validity, max(uids) if uids else since - 1, messages)


async def pull_mailbox(
    open_session: OpenSession, box: Mailbox, *, owner_user_id: int | None = None
) -> MailImportResult | None:
    """One pull: what was new becomes a batch like a dropped file's, the
    watermark moves, and the mailbox row says how it went. Nothing new,
    or nothing reachable, is None."""
    async with open_session() as db:
        row = await queries.mailbox(db, box.key)
        row_id, validity, uid_last = int(row.id), row.uidvalidity, row.uid_last
    try:
        fetched = await asyncio.to_thread(
            fetch_new,
            box,
            uidvalidity=validity,
            uid_last=uid_last,
            cap=PULL_BATCH,
        )
    except MailboxError as exc:
        logger.warning("mail.pull.failed", mailbox=box.label, error=str(exc))
        async with open_session() as db:
            await queries.mark_failed(db, row_id, str(exc))
        return None
    result = None
    if fetched.messages:
        sha = hashlib.sha256()
        for raw in fetched.messages:
            sha.update(raw)
        result = await ingest_messages(
            open_session,
            [parse.one(raw) for raw in fetched.messages],
            file_name=box.label,
            sha=sha.hexdigest(),
            source=SOURCE_IMAP,
            owner_user_id=owner_user_id,
        )
    async with open_session() as db:
        await queries.mark_pulled(
            db, row_id, uidvalidity=fetched.uidvalidity, uid_last=fetched.uid_last
        )
    logger.info("mail.pull.finished", mailbox=box.label, new=len(fetched.messages))
    return result


async def mail_pull_job() -> None:
    """Scheduled: pull the mailbox the secrets name. Nothing until one is."""
    box = await configured()
    if box is None:
        return
    await pull_mailbox(get_async_session, box)


async def mailbox_status(db: AsyncSession) -> MailboxStatus | None:
    """The mailbox the secrets name and how its last pull went; None
    when none is set."""
    box = await configured()
    if box is None:
        return None
    row = await queries.mailbox_state(db, box.key)
    return MailboxStatus(
        label=box.label,
        pulled_at=row.last_pulled_at if row else None,
        error=row.last_error if row else None,
    )


def _sign_in(box: Mailbox) -> None:
    with _signed_in(box):
        pass


async def verify_password(password: str) -> None:
    """One sign-in and out, so a typo fails at the paste and is never stored."""
    found = await secrets.get_many(HOST, USER)
    host, user = found.get(HOST), found.get(USER)
    if not (host and user):
        raise SecretUncheckedError(f"set {HOST} and {USER} first.")
    try:
        await asyncio.to_thread(_sign_in, Mailbox(host, user, DEFAULT_FOLDER, password))
    except MailboxRefusedError as exc:
        raise SecretRejectedError(f"{exc}.") from None
    except MailboxError as exc:
        raise SecretUncheckedError(f"{exc}.") from None


OWNER = "Mail (IMAP)"
# What the pull reads (``app.core.secrets``). The host, address and
# folder are safe to show whole; the app password is verified by one
# sign-in before it is stored.
SECRETS = (
    Secret(HOST, owner=OWNER, label="IMAP host", secret=False),
    Secret(USER, owner=OWNER, label="Mailbox address", secret=False),
    Secret(FOLDER, owner=OWNER, label="Folder or label", secret=False),
    Secret(PASSWORD, owner=OWNER, label="App password", verify=verify_password),
)
