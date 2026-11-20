"""Reading a mailbox export: what a message is, once it is out of the inbox.

Pure - bytes in, messages out, no database. Everything the pipeline
downstream needs comes off the headers and the parts, and the stdlib
already knows how to read both an mbox and an .eml.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.services.mail import parse
from tests._mbox import PDF, eml_bytes, mbox_bytes, message


class TestWhatAFileIs:
    def test_an_export_and_a_single_message_are_both_mail(self) -> None:
        assert parse.is_mail_export("All mail Including Spam and Trash.mbox")
        assert parse.is_mail_export("Your claim.eml")
        assert not parse.is_mail_export("statement.pdf")
        assert not parse.is_mail_export("export.csv")
        assert not parse.is_mail_export(None)

    def test_an_mbox_yields_every_message(self) -> None:
        data = mbox_bytes([message(subject="one"), message(subject="two")])
        read = parse.messages(data, "export.mbox")
        assert [m.subject for m in read] == ["one", "two"]

    def test_an_eml_yields_the_one_message(self) -> None:
        read = parse.messages(eml_bytes(message(subject="just this")), "x.eml")
        assert [m.subject for m in read] == ["just this"]

    def test_a_mailbox_past_the_cap_stops_at_the_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The rest is skipped with a warning, not a failed import: the
        first messages still file."""
        monkeypatch.setattr(settings, "MAIL_IMPORT_MAX_MESSAGES", 2)
        data = mbox_bytes([message(subject=s) for s in ("one", "two", "three")])

        read = parse.messages(data, "export.mbox")

        assert [m.subject for m in read] == ["one", "two"]


class TestWhatAMessageCarries:
    def test_the_sender_is_split_into_who_and_where(self) -> None:
        [read] = parse.messages(
            mbox_bytes([message(sender="Example Insurer <Claims@Insurer.Example>")]),
            "x.mbox",
        )
        assert read.from_name == "Example Insurer"
        # Lower-cased at the edge, once: an address is matched, never shown
        # back with somebody else's capitalisation.
        assert read.from_address == "claims@insurer.example"

    def test_the_message_id_is_the_identity(self) -> None:
        """RFC 5322 makes it unique per message; a re-export of an
        overlapping range must dedupe on it, not on subject or date."""
        [read] = parse.messages(
            mbox_bytes([message(message_id="<abc123@mail.example.com>")]), "x.mbox"
        )
        assert read.message_id == "<abc123@mail.example.com>"

    def test_a_message_with_no_id_gets_a_stable_one(self) -> None:
        """Some senders omit it. Two imports of the same file must still
        agree it is one message, so the fallback is derived from the
        headers, not minted fresh each time."""
        one = message()
        del one["Message-ID"]
        first = parse.messages(eml_bytes(one), "x.eml")[0].message_id
        again = parse.messages(eml_bytes(one), "x.eml")[0].message_id
        assert first == again and first

    def test_the_date_is_when_it_was_sent_as_stored(self) -> None:
        """Naive UTC, the timestamp columns' clock: Postgres refuses an
        aware value for them (a real import, 2026-11-20)."""
        sent = datetime(2026, 8, 27, 4, 5, tzinfo=timezone(timedelta(hours=-5)))
        [read] = parse.messages(mbox_bytes([message(sent=sent)]), "x.mbox")
        assert read.sent_at == datetime(2026, 8, 27, 9, 5)

    def test_attachments_come_off_as_files(self) -> None:
        [read] = parse.messages(
            mbox_bytes(
                [
                    message(
                        attachments=[
                            ("statement.pdf", "application/pdf", PDF),
                            ("eob.png", "image/png", b"\x89PNG\r\n\x1a\n"),
                        ]
                    )
                ]
            ),
            "x.mbox",
        )
        assert [(a.filename, a.media_type) for a in read.attachments] == [
            ("statement.pdf", "application/pdf"),
            ("eob.png", "image/png"),
        ]
        assert read.attachments[0].data == PDF

    def test_the_body_is_not_an_attachment(self) -> None:
        [read] = parse.messages(mbox_bytes([message(body="hello")]), "x.mbox")
        assert read.attachments == []

    def test_a_file_that_is_not_mail_is_refused_by_name(self) -> None:
        with pytest.raises(parse.NotMailError):
            parse.messages(b"%PDF-1.4", "statement.pdf")


class TestWhatIsNotPaper:
    """A notification that only links to a statement carries no paper:
    what it carries is a logo and a banner embedded in the HTML, email
    chrome that must not be filed (and then paid for to read)."""

    def test_images_embedded_in_the_body_are_not_attachments(self) -> None:
        chrome = message(
            inline_images=[("logo.png", b"\x89PNG"), ("banner.png", b"\x89PNG")]
        )
        [read] = parse.messages(eml_bytes(chrome), "x.eml")
        assert read.attachments == []

    def test_a_real_attachment_beside_embedded_images_is_still_paper(self) -> None:
        both = message(
            inline_images=[("logo.png", b"\x89PNG")],
            attachments=[("statement.pdf", "application/pdf", PDF)],
        )
        [read] = parse.messages(eml_bytes(both), "x.eml")
        assert [a.filename for a in read.attachments] == ["statement.pdf"]


class TestTheBodyIsTheLetter:
    """Much of what an agency sends has no attachment: the reminder or the
    explanation of benefits is the body. That mail IS the letter. No HTML
    rendering, no remote content: the text part is the letter, and an
    HTML-only mail is flattened."""

    def test_a_plain_body_is_kept_as_written(self) -> None:
        [read] = parse.messages(
            eml_bytes(message(body="Your claim was paid.")), "x.eml"
        )
        assert read.body_text == "Your claim was paid."

    def test_an_html_only_body_is_flattened_to_text(self) -> None:
        [read] = parse.messages(
            eml_bytes(
                message(body="Dear Sam", inline_images=[("logo.png", b"\x89PNG")])
            ),
            "x.eml",
        )
        assert "Dear Sam" in read.body_text
        assert "<" not in read.body_text and "cid:" not in read.body_text

    def test_styles_and_scripts_are_not_words(self) -> None:
        mail = message()
        mail.set_content(
            "<html><head><style>.x{color:red}</style></head>"
            "<body><script>track()</script><p>Sign in at provider.example</p>"
            "<p>800-555-0167</p></body></html>",
            subtype="html",
        )
        [read] = parse.messages(eml_bytes(mail), "x.eml")
        assert "color:red" not in read.body_text and "track()" not in read.body_text
        assert "Sign in at provider.example" in read.body_text
        # Block tags become line breaks, so a phone stays on its own line.
        assert "800-555-0167" in read.body_text.splitlines()
