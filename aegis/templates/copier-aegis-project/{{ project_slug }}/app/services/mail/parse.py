"""Bytes to messages. Pure: no database, no network, nothing stored.

Both shapes a mail provider hands out are stdlib: a mailbox export is an
``.mbox``, "Download message" saves an ``.eml``, and ``mailbox`` and
``email`` read them. Everything downstream needs is on the headers and
the parts, so this is the whole reader.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
import hashlib
from itertools import islice
import mailbox
from pathlib import Path
import tempfile

from app.core.config import settings
from app.core.html_text import flatten
from app.core.log import logger
from app.core.time import as_stored

MAIL_SUFFIXES = (".mbox", ".eml")


class NotMailError(ValueError):
    """The file is not a mailbox export or a saved message."""


@dataclass(frozen=True)
class Attachment:
    filename: str
    media_type: str | None
    data: bytes


@dataclass(frozen=True)
class ParsedMessage:
    """One message, as the pipeline reads it.

    ``message_id`` is the identity - RFC 5322 makes it unique per
    message, so a re-export of an overlapping range dedupes on it and
    nothing else. ``from_address`` is lower-cased once, here.
    """

    message_id: str
    from_address: str
    from_name: str
    subject: str
    sent_at: datetime | None
    # The text part, or the HTML part flattened to text. No rendering, no
    # remote content: a document that phones home when opened is a
    # tracking pixel with a filename.
    body_text: str = ""
    attachments: list[Attachment] = field(default_factory=list)


def is_mail_export(filename: str | None) -> bool:
    """Whether the file is a mailbox export or a saved message, by name."""
    return bool(filename) and str(filename).lower().endswith(MAIL_SUFFIXES)


def messages(data: bytes, filename: str) -> list[ParsedMessage]:
    """Every message in the file, in file order."""
    if not is_mail_export(filename):
        raise NotMailError(
            f"{filename!r} is not a mailbox export (.mbox) or a saved message (.eml)."
        )
    if filename.lower().endswith(".eml"):
        return [one(data)]
    # mailbox.mbox reads a path, not bytes: it seeks. A temp file is the
    # honest way in, and it is gone before this returns.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "export.mbox"
        path.write_bytes(data)
        box = mailbox.mbox(
            path, factory=lambda f: message_from_bytes(f.read(), policy=policy.default)
        )
        try:
            # Counting is a scan for "From " lines; only what is kept is parsed.
            total, cap = len(box), settings.MAIL_IMPORT_MAX_MESSAGES
            if total > cap:
                logger.warning("mail.import.capped", kept=cap, skipped=total - cap)
            return [_read(one) for one in islice(box, cap)]
        finally:
            box.close()


def one(data: bytes) -> ParsedMessage:
    """One message from its raw bytes: a saved ``.eml``, or a message as
    an IMAP server hands it over."""
    return _read(message_from_bytes(data, policy=policy.default))


def _read(mail: EmailMessage) -> ParsedMessage:
    name, address = parseaddr(str(mail.get("From") or ""))
    return ParsedMessage(
        message_id=_identity(mail),
        from_address=address.lower(),
        from_name=name.strip(),
        subject=str(mail.get("Subject") or "").strip(),
        sent_at=_sent(mail),
        body_text=_body(mail),
        attachments=[
            Attachment(
                filename=part.get_filename() or "attachment",
                media_type=part.get_content_type(),
                data=part.get_payload(decode=True) or b"",
            )
            for part in mail.iter_attachments()
            if _is_paper(part)
        ],
    )


def _is_paper(part: EmailMessage) -> bool:
    """A part the sender ATTACHED, as opposed to one the body embeds.

    An HTML email carries its logos as ``inline`` parts with a
    ``Content-ID`` the body references by ``cid:``. When the whole
    message is ``multipart/related`` - the shape many provider notices
    arrive in - stdlib's ``iter_attachments()`` hands those straight
    back, and a logo and a banner would be filed as documents and each
    read by a model. Inline plus a Content-ID is chrome; everything else
    is paper.
    """
    return not (part.get_content_disposition() == "inline" and part.get("Content-ID"))


def _identity(mail: EmailMessage) -> str:
    """The Message-ID, or - where a sender omitted one - a hash of the
    headers that make a message what it is. Derived, not minted: two
    imports of the same file have to agree it is one message."""
    given = str(mail.get("Message-ID") or "").strip()
    if given:
        return given
    stamp = "\n".join(str(mail.get(h) or "") for h in ("From", "To", "Date", "Subject"))
    return f"<sha256:{hashlib.sha256(stamp.encode()).hexdigest()}>"


def _sent(mail: EmailMessage) -> datetime | None:
    raw = mail.get("Date")
    if not raw:
        return None
    try:
        when = parsedate_to_datetime(str(raw))
    except (TypeError, ValueError):
        return None
    # One clock, the columns' naive UTC. A naive date is taken as UTC
    # rather than guessed at.
    return as_stored(when)


def _body(mail: EmailMessage) -> str:
    """The text part as written; failing that, the HTML part as words."""
    part = mail.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    content = str(part.get_content())
    if part.get_content_type() == "text/html":
        return flatten(content)
    return content.strip()
