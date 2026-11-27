"""``ai conversations`` lists them (#1835).

The asyncio.run -> await rewrite (#1821) left
``await list_conversations(...)[:limit]``, which slices the coroutine
before awaiting it, so the command died with a TypeError every time.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from tests._cli import invoke


def _conversation(id: str, title: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        title=title,
        get_message_count=lambda: 2,
        updated_at=datetime(2026, 10, 25, 9, 30, tzinfo=UTC),
    )


def test_it_lists_up_to_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.ai.service import AIService

    async def listed(self: Any, user_id: str) -> list[SimpleNamespace]:
        return [
            _conversation("a" * 32, "Water heater"),
            _conversation("b" * 32, "Taxes"),
        ]

    monkeypatch.setattr(AIService, "list_conversations", listed)

    result = invoke(["ai", "conversations", "--limit", "1"])

    assert result.exit_code == 0, result.output
    assert "Water heater" in result.output
    assert "Taxes" not in result.output


def test_an_interactive_chat_is_the_named_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``-u`` picks the conversation resumed, so the session's turns are
    that user's too: a turn under another name finds no conversation."""
    from app.cli.ai import chat
    from app.services.ai.service import AIService

    async def listed(self: Any, user_id: str) -> list[SimpleNamespace]:
        return [_conversation("a" * 32, "Water heater")]

    seen: list[tuple[str | None, str]] = []

    async def session(_: Any, conversation_id: str | None, user_id: str) -> None:
        seen.append((conversation_id, user_id))

    monkeypatch.setattr(AIService, "list_conversations", listed)
    monkeypatch.setattr(chat, "_interactive_chat_session", session)

    result = invoke(["ai", "chat", "-u", "alice"])

    assert result.exit_code == 0, result.output
    assert seen == [("a" * 32, "alice")]
