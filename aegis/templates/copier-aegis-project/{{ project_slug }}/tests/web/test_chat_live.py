"""A live call from the chat surface: one path for every engine.

The page opens the mount's WebSocket; the server opens the engine's
realtime session and carries the audio both ways, telling the page what
the call is doing. Tested on the Overseer's mount; every mount gets the
same socket under its own path.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    PartEndEvent,
    RealtimeTurnCompleteEvent,
    SpeechPart,
    ToolCallPart,
)
import pytest
from starlette.websockets import WebSocketDisconnect

from app.components.web_frontend.overseer_ai_chat import OVERSEER
from app.components.web_frontend.routes.partials import chat_live
from app.components.web_frontend.routes.partials import (
    overseer_ai_chat as overseer_mount,
)
from app.services.ai.domains.voice import realtime_calls
from app.services.system.models import ComponentStatus
from tests._realtime import VOICE, FakeRealtime
from tests.web.dom import one
from tests.web.overseer import sign_in, status_with

PAGE = "/overseer/services/ai/chat"
SOCKET = f"{OVERSEER.path}/live/ws"


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    ai = ComponentStatus(name="ai", message="AI", metadata={"engine": "pydantic-ai"})
    sign_in(app, monkeypatch, status_with(services=[ai]))

    async def signed_in() -> None:
        return None

    # The socket's own guard reads the session cookie; signed in here.
    app.dependency_overrides[overseer_mount._signed_in_socket] = signed_in
    return TestClient(app)


ENGINE = SimpleNamespace(
    key="gemini-live",
    instructions="## THIS IS A LIVE VOICE CALL",
    max_output_tokens=1_200,
    llm=SimpleNamespace(
        model_id="gemini-3.8-live",
        title="Gemini 3.8 Live",
        served_by=SimpleNamespace(slug="google"),
    ),
)


@pytest.fixture
def gemini(monkeypatch: pytest.MonkeyPatch) -> FakeRealtime:
    """A call on Gemini Live, its session played by a fake: you say hi, a
    step runs, it answers, and it ends the call."""
    fake = FakeRealtime(
        [
            PartEndEvent(index=0, part=SpeechPart(speaker="user", transcript="Hi")),
            FunctionToolCallEvent(
                part=ToolCallPart(
                    tool_name="run_code",
                    args={"code": "result = await report()"},
                    tool_call_id="t1",
                )
            ),
            PartEndEvent(
                index=1, part=SpeechPart(speaker="assistant", transcript="Hello!")
            ),
            FunctionToolCallEvent(
                part=ToolCallPart(
                    tool_name=realtime_calls.END_CALL, args={}, tool_call_id="e1"
                )
            ),
            RealtimeTurnCompleteEvent(),
        ],
        after_audio=True,
    )

    async def engine_now() -> tuple[Any, dict[str, Any]]:
        return ENGINE, {"label": ENGINE.llm.title}

    async def built(*args: Any, **kwargs: Any) -> Any:
        return fake

    monkeypatch.setattr(chat_live, "_engine_now", engine_now)
    monkeypatch.setattr(realtime_calls, "realtime_for", built)
    return fake


class TestTheControls:
    def test_the_phone_sits_beside_the_mic_and_knows_its_socket(
        self, client: TestClient
    ) -> None:
        button = one(client.get(PAGE).text, "#chat-composer button#chat-live")
        assert button.get("data-relay") == SOCKET
        assert "mic-worklet" in (button.get("data-worklet") or "")
        assert button.get("data-state") == "idle"

    def test_the_phone_draws_the_agent_at_work(self, client: TestClient) -> None:
        """A step running is its own state, not the connecting spinner."""
        button = one(client.get(PAGE).text, "button#chat-live")
        drawn = {
            e.get("data-mic-visual") for e in button.cssselect("[data-mic-visual]")
        }
        assert drawn == {"recording", "thinking", "speaking", "working"}

    def test_the_call_bar_waits_hidden_in_the_page(self, client: TestClient) -> None:
        page = client.get(PAGE).text
        assert one(page, "#chat-call").get("hidden") is not None
        assert one(page, "#chat-call button#chat-mute").get("aria-pressed") == "false"
        one(page, "#chat-call button#chat-hang-up")
        for figure in ("timer", "cost", "engine"):
            one(page, f"#chat-call [data-call-{figure}]")
        for state in ("live", "working", "muted"):
            one(page, f"template#chat-mic-states [data-state={state}]")

    def test_a_card_drawn_mid_call_has_a_place_in_the_thread(
        self, client: TestClient
    ) -> None:
        one(client.get(PAGE).text, "template#chat-live-card")


class TestTheCall:
    def test_it_carries_the_audio_both_ways(
        self, client: TestClient, gemini: FakeRealtime
    ) -> None:
        heard: list[bytes] = []
        told: list[dict[str, Any]] = []
        with client.websocket_connect(SOCKET) as ws:
            ready = ws.receive_json()
            ws.send_bytes(b"\x10\x20")
            for _ in range(20):  # a bound, never a hang
                message = ws.receive()
                if message.get("bytes"):
                    heard.append(message["bytes"])
                elif message.get("text"):
                    told.append(json.loads(message["text"]))
                if heard and any(t["type"] == "saved" for t in told):
                    break

        assert ready["type"] == "ready"
        assert (ready["input_rate"], ready["output_rate"]) == (16_000, 24_000)
        assert ready["conversation_id"]  # a call without one starts one
        assert ready["engine"] == {"label": "Gemini 3.8 Live"}
        assert heard == [VOICE]  # its voice, as the model spoke it
        assert gemini.live.audio == [b"\x10\x20"]  # yours, as the page sent it
        assert gemini.live.sent == [chat_live.GREETING]  # it speaks first
        assert [t["text"] for t in told if t["type"] == "said"] == ["Hello!"]
        # Each step as it runs, labelled as the thread's trail labels it.
        steps = [t.get("label") for t in told if t["type"] == "working"]
        assert steps == ["run_code: result = await report()"]
        # It ended the call: the page hangs up once the goodbye has played.
        assert {"type": "hang_up"} in told
        assert told[-1]["type"] == "saved"  # the thread reloads

    def test_a_dropped_call_picks_up_where_it_stopped(
        self, client: TestClient, gemini: FakeRealtime, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            realtime_calls, "resumed", lambda conversation: "How much is left?"
        )
        with client.websocket_connect(SOCKET) as ws:
            ws.receive_json()
            ws.send_bytes(b"\x10\x20")  # the fake plays once it hears you
        (opening,) = gemini.live.sent
        assert "How much is left?" in opening

    def test_no_engine_on_offer_is_refused(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def none_on_offer() -> tuple[None, None]:
            return None, None

        monkeypatch.setattr(chat_live, "_engine_now", none_on_offer)
        with (
            pytest.raises(WebSocketDisconnect) as refused,
            client.websocket_connect(SOCKET) as ws,
        ):
            ws.receive_json()
        assert refused.value.code == 1008


def test_a_call_into_a_conversation_does_not_meet_them_again() -> None:
    """A call into a conversation under way greets them as someone it
    knows; a first call greets; nothing to pick up is not a resume."""
    under_way = SimpleNamespace(messages=[SimpleNamespace(role="user", metadata={})])
    assert chat_live.opening(under_way) == chat_live.CONTINUING
    assert chat_live.opening(None) == chat_live.GREETING
    assert chat_live.opening(SimpleNamespace(messages=[])) == chat_live.GREETING


def test_a_caller_who_is_not_signed_in_is_refused(app: FastAPI) -> None:
    """The socket's guard reads the session cookie: none, no call."""
    with (
        pytest.raises(WebSocketDisconnect) as refused,
        TestClient(app).websocket_connect(SOCKET) as ws,
    ):
        ws.receive_json()
    assert refused.value.code == 1008
