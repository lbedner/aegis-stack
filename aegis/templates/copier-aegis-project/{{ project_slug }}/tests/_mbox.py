"""Hand-built mailboxes for tests, the way ``_pdf.py`` builds PDFs.

Generated rather than checked in, so the suite carries no mail fixtures
and every test says exactly what its messages contain.
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
import mailbox
from pathlib import Path
import tempfile


def message(
    *,
    sender: str = "Example Insurer <claims@insurer.example>",
    to: str = "sam@example.com",
    subject: str = "Your claim has been processed",
    body: str = "Your claim was processed. See the attached statement.",
    sent: datetime | None = None,
    message_id: str | None = None,
    attachments: list[tuple[str, str, bytes]] | None = None,
    inline_images: list[tuple[str, bytes]] | None = None,
) -> EmailMessage:
    """One message. ``attachments`` are ``(filename, media_type, bytes)``.

    ``inline_images`` are ``(filename, bytes)`` embedded in an HTML body
    and referenced by ``cid:`` - the logos every HTML newsletter carries.
    Built as ``multipart/related`` at the top level, the shape a real
    provider's notification arrives in, and the one stdlib's
    ``iter_attachments()`` hands straight back.
    """
    mail = EmailMessage()
    mail["From"] = sender
    mail["To"] = to
    mail["Subject"] = subject
    mail["Date"] = format_datetime(sent or datetime(2026, 9, 1, 14, 30, tzinfo=UTC))
    mail["Message-ID"] = message_id or make_msgid(domain="example.com")
    if inline_images:
        tags = "".join(f'<img src="cid:{name}">' for name, _ in inline_images)
        mail.set_content(
            f"<html><body><p>{body}</p>{tags}</body></html>", subtype="html"
        )
        for name, data in inline_images:
            mail.add_related(
                data,
                maintype="image",
                subtype="png",
                cid=f"<{name}>",
                filename=name,
                disposition="inline",
            )
    else:
        mail.set_content(body)
    for filename, media_type, data in attachments or []:
        main, _, sub = media_type.partition("/")
        mail.add_attachment(data, maintype=main, subtype=sub, filename=filename)
    return mail


def mbox_bytes(messages: list[EmailMessage]) -> bytes:
    """A whole mailbox, as a provider's export writes one."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "export.mbox"
        box = mailbox.mbox(path)
        for one in messages:
            box.add(one)
        box.flush()
        box.close()
        return path.read_bytes()


def eml_bytes(one: EmailMessage) -> bytes:
    """A single message, as a mail client's "Download message" saves one."""
    return one.as_bytes()


# A tiny valid PDF, so an attachment is something the shelf can hold.
PDF = (
    b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
)
