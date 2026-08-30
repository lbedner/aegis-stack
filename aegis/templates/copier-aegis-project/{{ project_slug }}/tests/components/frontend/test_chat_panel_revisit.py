"""Returning to the Chat tab refreshes its pending-change cards.

A resolution made on ANOTHER surface (approving on the Overview tab)
must reach a card the open chat already rendered - the modal's
``refresh_on_revisit`` hook fires on tab return, and the panel re-reads
every card it has shown from the queue's current truth.
"""

from typing import Any

import pytest

from tests.components.frontend._tree import rendered

_CHANGE = {
    "id": 7,
    "change_type": "transaction.categorize",
    "title": "Categorize a transaction",
    "status": "pending",
    "display": [{"label": "Category", "value": "Uncategorized → Groceries"}],
}


async def _noop_action(change_id: int, action: str) -> dict[str, Any] | None:
    return None


def _panel() -> Any:
    from app.components.frontend.controls.chat.panel import ChatPanel

    return ChatPanel(agent_slug="finance-assistant", surface="finance", user_id="0")


class TestRevisitRefreshesCards:
    def test_the_panel_opts_into_the_revisit_hook(self) -> None:
        assert callable(getattr(_panel(), "refresh_on_revisit", None))

    @pytest.mark.asyncio
    async def test_a_revisit_rereads_every_rendered_card(self) -> None:
        from app.components.frontend.controls.chat.components import (
            PendingChangeCard,
        )

        panel = _panel()
        card = PendingChangeCard(dict(_CHANGE), on_action=_noop_action)
        panel._pending_cards.append(card)

        async def fetch(change_id: int) -> dict[str, Any] | None:
            assert change_id == 7
            return {**_CHANGE, "status": "approved"}

        panel._change_fetch = fetch  # type: ignore[method-assign]
        await panel._refresh_pending_cards()

        assert "Approved" in rendered(card)

    @pytest.mark.asyncio
    async def test_a_new_conversation_drops_the_tracked_cards(self) -> None:
        """Cards from a conversation the transcript no longer shows must
        not be refetched forever."""
        from app.components.frontend.controls.chat.components import (
            PendingChangeCard,
        )

        panel = _panel()
        panel._pending_cards.append(
            PendingChangeCard(dict(_CHANGE), on_action=_noop_action)
        )

        panel._clear_transcript()

        assert panel._pending_cards == []
