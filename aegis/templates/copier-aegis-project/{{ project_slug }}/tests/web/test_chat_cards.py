"""Cards the assistant draws, in the thread (tested on the Overseer's mount).

A drawn card rides the trace as a marker; the settled message places a
loader for it, and the card route draws the kind's template from the
card's frozen payload. The trend is a line chart drawn by the app's own
chart code; a card that is gone says so quietly (200, never 404).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.backend.api.ai.service import ai_service
from app.components.web_frontend.overseer_ai_chat import OVERSEER
from app.services.ai.models import AIProvider, MessageRole
from app.services.ai.models.chat_card import ChatCard
from app.services.system.models import ComponentStatus
from tests.web.dom import none, one, select, text
from tests.web.overseer import sign_in, status_with

CARDS = f"{OVERSEER.path}/cards"


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    ai = ComponentStatus(name="ai", message="AI", metadata={"engine": "pydantic-ai"})
    sign_in(app, monkeypatch, status_with(services=[ai]))
    return TestClient(app)


@pytest.fixture
def hx(client: TestClient) -> TestClient:
    client.headers["HX-Request"] = "true"
    return client


PAYLOADS: dict[str, dict[str, Any]] = {
    "trend": {
        "title": "Groceries by month",
        "measure": "Spent",
        "rows": [
            {"date": "2026-08-01", "value": 61_250},
            {"date": "2026-09-01", "value": 58_900},
        ],
    },
    "bar": {
        "title": "Top payees, Sep 1 - Sep 25",
        "measure": "Spent",
        "rows": [
            {"label": "ShopRite", "value": 40_000},
            {"label": "Amazon", "value": 25_000},
            {"label": "Starbucks", "value": 10_000},
        ],
    },
    "compare": {
        "title": "Eating out",
        "measure": "Spent",
        "before_label": "August",
        "before": 40_000,
        "after_label": "September",
        "after": 30_000,
    },
    "pie": {
        "title": "Spending by category, Jul - Sep 2026",
        "measure": "Spent",
        "rows": [
            {"label": "Long Term Care", "value": 610_000},
            {"label": "Groceries", "value": 369_354},
        ],
    },
    "table": {
        "title": "State Farm by month",
        "columns": ["Month", "Charged", "Note"],
        "rows": [{"label": "Aug", "values": ["$18.00", "Paid late; letter sent"]}],
    },
}


@pytest.fixture
async def drawn() -> dict[str, str]:
    """A conversation whose answer drew one card of each kind. Stored the
    way the app stores them: through its own session opener, which the
    card route reads with."""
    from app.core.db import get_async_session

    conversation = await ai_service.conversation_manager.create_conversation(
        provider=AIProvider.OLLAMA,
        model="gpt-5.6-luna",
        user_id=OVERSEER.user,
        surface=OVERSEER.surface,
    )
    ids = {}
    async with get_async_session() as session:
        for kind, payload in PAYLOADS.items():
            card = ChatCard(conversation_id=conversation.id, kind=kind, payload=payload)
            session.add(card)
            ids[kind] = card.id
    conversation.add_message(MessageRole.USER, "Show me")
    reply = conversation.add_message(
        MessageRole.ASSISTANT,
        "Here it is.",
        metadata={
            "tool_trace": [
                {
                    "tool": "run_code",
                    "code": "await draw_card(...)",
                    "result": "ok",
                    "component": [{"kind": "chat_card", "id": ids["trend"]}],
                }
            ]
        },
    )
    await ai_service.conversation_manager.save_conversation(conversation)
    return {**ids, "conversation": conversation.id, "message": reply.id}


class TestInTheThread:
    def test_the_answer_places_a_loader_for_its_card(
        self, hx: TestClient, drawn: dict[str, str]
    ) -> None:
        html = hx.get(
            f"{OVERSEER.path}/messages/{drawn['conversation']}/{drawn['message']}"
        ).text
        loader = one(html, "[data-card-load]")
        assert loader.get("hx-get") == f"{CARDS}/{drawn['trend']}"
        assert loader.get("hx-trigger") == "load"


class TestTheCards:
    def test_a_trend_is_a_line_drawn_by_the_apps_chart_code(
        self, hx: TestClient, drawn: dict[str, str]
    ) -> None:
        html = hx.get(f"{CARDS}/{drawn['trend']}").text
        card = one(html, "[data-card=trend]")
        assert "Groceries by month" in text(card)
        canvas = one(html, "[data-card=trend] canvas[data-chart=line]")
        data = json.loads(text(one(html, f"#{canvas.get('data-chart-data')}")))
        # Cents in the payload, dollars on the chart - its axis is money.
        assert data["series"][0]["values"] == [612.5, 589.0]
        assert len(data["labels"]) == 2

    def test_a_bar_is_a_bar_chart(self, hx: TestClient, drawn: dict[str, str]) -> None:
        """Vertical bars in the order the assistant gave them, drawn by the app's
        chart code: the highest bright teal, the lowest violet, the rest a
        darker teal (Pulse's day-of-week chart)."""
        html = hx.get(f"{CARDS}/{drawn['bar']}").text
        canvas = one(html, "[data-card=bar] canvas[data-chart=bar]")
        data = json.loads(text(one(html, f"#{canvas.get('data-chart-data')}")))
        assert data["labels"] == ["ShopRite", "Amazon", "Starbucks"]
        (series,) = data["series"]
        assert series["values"] == [400.0, 250.0, 100.0]
        assert series["tones"] == ["high", "mid", "low"]

    def test_a_pie_is_a_doughnut(self, hx: TestClient, drawn: dict[str, str]) -> None:
        """Parts of a whole, drawn like the Overview's spending chart."""
        html = hx.get(f"{CARDS}/{drawn['pie']}").text
        canvas = one(html, "[data-card=pie] canvas[data-chart=doughnut]")
        data = json.loads(text(one(html, f"#{canvas.get('data-chart-data')}")))
        assert data["labels"] == ["Long Term Care", "Groceries"]
        assert data["series"][0]["values"] == [6100.0, 3693.54]

    def test_a_comparison_works_out_the_change_itself(
        self, hx: TestClient, drawn: dict[str, str]
    ) -> None:
        html = hx.get(f"{CARDS}/{drawn['compare']}").text
        assert text(one(html, "[data-card=compare] [data-change]")) == "-25.0%"

    def test_a_table_heads_every_column(
        self, hx: TestClient, drawn: dict[str, str]
    ) -> None:
        html = hx.get(f"{CARDS}/{drawn['table']}").text
        heads = select(html, "[data-card=table] th")
        assert [text(h) for h in heads] == ["Month", "Charged", "Note"]

    def test_figures_line_up_and_words_wrap(
        self, hx: TestClient, drawn: dict[str, str]
    ) -> None:
        """A column of figures sits right, for comparing; a column of words
        reads left and wraps, so the card widens with what it holds."""
        html = hx.get(f"{CARDS}/{drawn['table']}").text
        assert [text(h) for h in select(html, "th.text-right")] == ["Charged"]
        assert [text(c) for c in select(html, "td.text-right")] == ["$18.00"]
        assert [text(c) for c in select(html, "td.whitespace-normal")] == [
            "Paid late; letter sent"
        ]
        one(html, "[data-card=table][data-fit]")

    def test_a_card_opens_larger_in_the_dialog(
        self, hx: TestClient, drawn: dict[str, str]
    ) -> None:
        small = one(hx.get(f"{CARDS}/{drawn['bar']}").text, "[data-card=bar]")
        assert small.get("hx-get") == f"{CARDS}/{drawn['bar']}?size=large"

    def test_the_larger_card_is_a_dialog_body(
        self, hx: TestClient, drawn: dict[str, str]
    ) -> None:
        large = hx.get(f"{CARDS}/{drawn['bar']}", params={"size": "large"}).text
        none(large, "html")
        assert one(large, "[data-card=bar]").get("hx-get") is None

    @pytest.mark.parametrize("path_client", ["client", "hx"])
    def test_a_card_that_is_gone_says_so_quietly(
        self, request: pytest.FixtureRequest, path_client: str
    ) -> None:
        response = request.getfixturevalue(path_client).get(f"{CARDS}/nope")
        assert response.status_code == 200
        one(response.text, "[data-card-missing]")


class TestTheMessage:
    def test_the_card_is_the_one_the_reply_drew(self) -> None:
        from app.components.web_frontend.chat_surface import drawn_card_urls

        trace = [
            {"tool": "run_code", "component": [{"kind": "chat_card", "id": "abc"}]},
            {
                "tool": "propose",
                "component": {"kind": "pending_change", "pending_change_id": "7"},
            },
        ]
        assert drawn_card_urls(OVERSEER, trace) == [f"{CARDS}/abc"]

    def test_a_redraw_replaces_the_card_before_it(self) -> None:
        """One card per answer: a card drawn, then fixed and drawn again,
        shows once - the last one drawn."""
        from app.components.web_frontend.chat_surface import drawn_card_urls

        trace = [
            {"tool": "run_code", "component": [{"kind": "chat_card", "id": "first"}]},
            {"tool": "run_code", "component": [{"kind": "chat_card", "id": "fixed"}]},
        ]
        assert drawn_card_urls(OVERSEER, trace) == [f"{CARDS}/fixed"]
