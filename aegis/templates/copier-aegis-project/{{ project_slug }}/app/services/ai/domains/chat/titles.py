"""Conversation naming.

Small on purpose: the derivation is shared by every chat entry point
(sync, streaming), and ``conversation.py`` sits at its size budget.
"""


def conversation_title(message: str) -> str:
    """The first user message as a history-list title: one line, <=60 chars.

    Whitespace runs (including newlines) collapse to single spaces before
    truncating - a pasted multi-line message otherwise becomes a
    multi-line tile in every history list that renders the title.
    """
    flat = " ".join(message.split())
    return flat if len(flat) <= 60 else f"{flat[:57]}..."
