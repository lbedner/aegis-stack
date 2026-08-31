"""Chat image attachments: what the model actually receives.

The API accepts base64 image parts alongside the message; the service
turns them into multimodal user content for the model call and stamps a
marker into the stored history (later turns cannot replay the bytes,
but they should know a screenshot was there).
"""

import base64

import pytest

from app.services.ai.domains.chat.attachments import (
    ChatAttachment,
    annotate_attachments,
    build_user_content,
)

_PNG = base64.b64encode(b"\x89PNG fake bytes").decode()


def _shot(name: str = "order.png") -> ChatAttachment:
    return ChatAttachment(media_type="image/png", data_b64=_PNG, name=name)


class TestBuildUserContent:
    def test_no_attachments_is_the_plain_context_string(self) -> None:
        assert build_user_content("ctx", []) == "ctx"
        assert build_user_content("ctx", None) == "ctx"

    def test_attachments_ride_as_binary_content_after_the_text(self) -> None:
        from pydantic_ai.messages import BinaryContent

        content = build_user_content("ctx", [_shot(), _shot("b.jpg")])

        assert isinstance(content, list)
        assert content[0] == "ctx"
        assert all(isinstance(part, BinaryContent) for part in content[1:])
        assert content[1].data == b"\x89PNG fake bytes"
        assert content[1].media_type == "image/png"

    def test_undecodable_data_is_rejected(self) -> None:
        bad = ChatAttachment(media_type="image/png", data_b64="not base64!!!")

        with pytest.raises(ValueError, match="attachment"):
            build_user_content("ctx", [bad])


class TestAnnotateAttachments:
    def test_marker_names_what_was_attached(self) -> None:
        annotated = annotate_attachments("split this", [_shot(), _shot("b.jpg")])

        assert annotated == "split this\n\n[attached 2 images: order.png, b.jpg]"

    def test_single_image_reads_singular(self) -> None:
        assert annotate_attachments("hi", [_shot()]).endswith(
            "[attached 1 image: order.png]"
        )

    def test_no_attachments_leaves_the_message_alone(self) -> None:
        assert annotate_attachments("hi", []) == "hi"
        assert annotate_attachments("hi", None) == "hi"
