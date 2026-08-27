"""The first message names the conversation - as ONE line.

History lists render the title in a single-row tile; a pasted
multi-line message used to become a multi-line title and break the
layout, so the title flattens whitespace before truncating.
"""

from app.services.ai.domains.chat.titles import conversation_title


class TestConversationTitle:
    def test_a_short_message_is_the_title(self) -> None:
        assert conversation_title("Pay the dentist") == "Pay the dentist"

    def test_a_long_message_truncates_with_an_ellipsis(self) -> None:
        title = conversation_title("x" * 80)
        assert title == "x" * 57 + "..."
        assert len(title) == 60

    def test_newlines_and_runs_collapse_to_single_spaces(self) -> None:
        assert (
            conversation_title("what's\n\nmy   balance\tthis month")
            == "what's my balance this month"
        )

    def test_truncation_happens_after_flattening(self) -> None:
        message = ("word " * 20) + "\n\ntail"
        title = conversation_title(message)
        assert "\n" not in title
        assert len(title) == 60
