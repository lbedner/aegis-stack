"""Cards the assistant draws in a reply: a chart, a ranking, a comparison
or a table, under the answer that talks about it.

The model authors data, never layout: a ``kind``
selects a template the app wrote, the kind's schema is checked when the assistant
draws it, and the payload is frozen so the card shows what the assistant computed
beside the sentence that says it. ``draw_card`` runs inside ``run_code``
so rows the assistant computed are never retyped; the cards drawn during a script
ride that script's trace entry as markers, which is what the settled
message draws from.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.domains.chat import cards
from app.services.ai.domains.chat.cards import attach_cards, card_stage, draw_card
from app.services.ai.domains.chat.user_memory import memory_user
from app.services.ai.models.chat_card import ChatCard
from tests._session import opens

TREND = {
    "title": "Groceries by month, Apr - Sep 2026",
    "measure": "Spent",
    "rows": [
        {"date": "2026-04-01", "value": 61_250},
        {"date": "2026-05-01", "value": 58_900},
    ],
}


async def _drawn(
    kind: str, payload: Any
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with memory_user("0", conversation_id="conv-1"), card_stage() as staged:
        result = await draw_card(kind, payload)
    return result, staged


class TestDrawing:
    @pytest.mark.asyncio
    async def test_a_card_is_stored_frozen_and_marked_for_the_turn(
        self, async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cards, "get_async_session", opens(async_db_session))
        result, staged = await _drawn("trend", TREND)

        assert result["kind"] == "trend"
        card = await async_db_session.get(ChatCard, result["id"])
        assert card is not None
        assert (card.conversation_id, card.kind) == ("conv-1", "trend")
        assert card.payload["rows"][0] == {"date": "2026-04-01", "value": 61_250.0}
        assert staged == [{"kind": "chat_card", "id": result["id"]}]

    @pytest.mark.asyncio
    async def test_outside_a_turn_it_says_so(self) -> None:
        result = await draw_card("trend", TREND)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_an_unknown_kind_names_the_real_ones(self) -> None:
        result, staged = await _drawn("radar", TREND)
        assert all(name in result["error"] for name in cards.kind_names())
        assert staged == []

    @pytest.mark.asyncio
    async def test_a_bad_payload_says_what_fits(self) -> None:
        result, staged = await _drawn("trend", {"title": "x"})
        # Every fault at once, and the shape that would have worked.
        assert "measure" in result["error"] and "rows" in result["error"]
        assert "{title: str" in result["error"]
        assert staged == []

    @pytest.mark.asyncio
    async def test_a_card_is_a_top_ten_not_a_dump(self) -> None:
        rows = [{"label": f"Payee {n}", "value": n} for n in range(11)]
        result, staged = await _drawn(
            "bar", {"title": "Top payees", "measure": "Spent", "rows": rows}
        )
        assert "at most 10" in result["error"]
        assert staged == []

    @pytest.mark.asyncio
    async def test_a_pie_is_a_few_slices_not_a_confetti(self) -> None:
        rows = [{"label": f"Category {n}", "value": n + 1} for n in range(9)]
        result, staged = await _drawn(
            "pie", {"title": "Spending", "measure": "Spent", "rows": rows}
        )
        assert "at most 8" in result["error"]
        assert staged == []

    def test_every_kind_is_in_the_tools_own_description(self) -> None:
        for name in cards.kind_names():
            assert f"- {name}" in (draw_card.__doc__ or "")

    def test_a_table_names_its_label_column_too(self) -> None:
        with pytest.raises(ValueError, match="values"):
            cards.TablePayload(
                title="t",
                columns=["Payee", "Spent"],
                rows=[{"label": "a", "values": [1, 2]}],
            )


class TestTheTrail:
    def test_drawn_cards_ride_the_script_that_drew_them(self) -> None:
        trace: list[dict[str, Any]] = [{"tool": "run_code", "result": "ok"}]
        drawn = [{"kind": "chat_card", "id": "abc"}]

        attach_cards(trace, drawn)

        assert trace[-1]["component"] == [{"kind": "chat_card", "id": "abc"}]
        assert drawn == []  # drained: the next script starts clean

    def test_nothing_drawn_leaves_the_trace_alone(self) -> None:
        trace: list[dict[str, Any]] = [{"tool": "run_code", "result": "ok"}]
        attach_cards(trace, [])
        assert "component" not in trace[-1]


def test_it_is_a_tool_an_agent_can_be_granted() -> None:
    from app.core.tools import get_tool

    tool = get_tool("draw_card")
    # It shows what the script computed and changes nothing: a read, so it
    # runs inside run_code beside the code that computed the rows.
    assert tool is not None and tool.effect == "read"
