"""A live call from the chat surface: one path for every engine.

The page opens the mount's WebSocket; the server opens the engine's
realtime session and carries the audio both ways, telling the page what
the call is doing. Tested on the Overseer's mount; every mount gets the
same socket under its own path.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from importlib.util import find_spec
import json
import queue
import threading
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    PartEndEvent,
    PartStartEvent,
    RealtimeTurnCompleteEvent,
    SpeechPart,
    ToolCallPart,
)
import pytest
from starlette.websockets import WebSocketDisconnect

from app.components.web_frontend import overseer_access
from app.components.web_frontend.chat_surface import ChatSurface
from app.components.web_frontend.overseer_ai_chat import OVERSEER
from app.components.web_frontend.routes.partials import chat_live
from app.core.tools import current_owner_user_id, current_subject
from app.services.ai.domains.voice import realtime_calls
from app.services.shared.deps import get_optional_owner_user_id
from app.services.ai.domains.chat.page_actions import page_action
from tests._pages import LANDING
from tests._realtime import ENGINE, VOICE, FakeRealtime
from tests.web.dom import one
from tests.web.overseer import AI, sign_in, status_with

PAGE = "/overseer/services/ai/chat"
SOCKET = f"{OVERSEER.path}/live/ws"


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    sign_in(app, monkeypatch, status_with(services=[AI]))

    async def signed_in() -> None:
        return None

    # The socket's own guard reads the session cookie; signed in here.
    app.dependency_overrides[overseer_access.overseer_socket_gate] = signed_in
    return TestClient(app)


@pytest.fixture
def gemini(monkeypatch: pytest.MonkeyPatch) -> FakeRealtime:
    """A call on Gemini Live, its session played by a fake: you say hi, a
    step runs, it answers, and it ends the call."""
    fake = FakeRealtime(
        [
            PartStartEvent(index=0, part=SpeechPart(speaker="user", transcript="")),
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
        fake.built = kwargs  # who she was built for
        return fake

    monkeypatch.setattr(chat_live, "_engine_now", engine_now)
    monkeypatch.setattr(realtime_calls, "realtime_for", built)
    return fake


@pytest.fixture
def ended(monkeypatch: pytest.MonkeyPatch) -> threading.Event:
    """Set once the server has finished the call, its last writes made.

    The test client cancels the app as it leaves the socket, so a call still
    saving would be cut off mid-write and leak its database connection; a
    later test's teardown then hangs collecting it. A test hangs up and
    waits for this before it leaves."""
    done = threading.Event()
    drive = realtime_calls.drive

    async def driven(*args: Any, **kwargs: Any) -> Any:
        try:
            return await drive(*args, **kwargs)
        finally:
            done.set()

    monkeypatch.setattr(realtime_calls, "drive", driven)
    return done


@pytest.fixture
def ends() -> tuple[queue.Queue[str], Callable[[ChatSurface, str], Awaitable[None]]]:
    """How each call ended, as a mount's ``on_call_end`` heard it.

    The hook runs after the call's last writes, so waiting on it is
    waiting for the server to finish the call (``ended``)."""
    heard: queue.Queue[str] = queue.Queue()

    async def on_call_end(bound: ChatSurface, how: str) -> None:
        heard.put(how)

    return heard, on_call_end


async def _let_in() -> None:
    return None


async def _no_engine() -> tuple[None, None]:
    return None, None


def _calls(mount: ChatSurface) -> TestClient:
    """A mount's socket alone, its caller signed in as owner 7."""
    calls = FastAPI()
    calls.include_router(chat_live.live_router(mount, _let_in))

    async def owner() -> int:
        return 7

    calls.dependency_overrides[get_optional_owner_user_id] = owner
    return TestClient(calls)


def _hear(ws: Any, until: str) -> tuple[list[bytes], list[dict[str, Any]]]:
    """What the page heard and was told, up to the first event of a type."""
    heard: list[bytes] = []
    told: list[dict[str, Any]] = []
    for _ in range(50):  # a bound, never a hang
        message = ws.receive()
        if message.get("bytes"):
            heard.append(message["bytes"])
        elif message.get("text"):
            told.append(json.loads(message["text"]))
            if told[-1]["type"] == until:
                break
    return heard, told


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
        # The quiet, counted down to the hang-up on the status line.
        one(page, "template#chat-mic-states [data-state=hanging-up] [data-countdown]")

    def test_a_card_drawn_mid_call_has_a_place_in_the_thread(
        self, client: TestClient
    ) -> None:
        one(client.get(PAGE).text, "template#chat-live-card")

    def test_her_steps_show_in_the_thread_as_she_takes_them(
        self, client: TestClient
    ) -> None:
        """A call's turn shows each step as it runs, under her name, as a
        typed turn's do (2026-10-24: they showed only in the status line)."""
        turn = one(client.get(PAGE).text, "template#chat-live-turn")
        assert turn.xpath(".//*[@data-trail]")


class TestTheCall:
    def test_it_carries_the_audio_both_ways(
        self, client: TestClient, gemini: FakeRealtime, ended: threading.Event
    ) -> None:
        with client.websocket_connect(SOCKET) as ws:
            ready = ws.receive_json()
            ws.send_bytes(b"\x10\x20")
            heard, told = _hear(ws, "saved")
            ws.close()
            assert ended.wait(5)

        assert ready["type"] == "ready"
        assert (ready["input_rate"], ready["output_rate"]) == (16_000, 24_000)
        assert ready["conversation_id"]  # a call without one starts one
        assert ready["engine"] == {"label": "Gemini 3.8 Live"}
        assert heard == [VOICE]  # its voice, as the model spoke it
        assert gemini.live.audio == [b"\x10\x20"]  # yours, as the page sent it
        assert gemini.live.sent == [chat_live.GREETING]  # it speaks first
        # You were heard from your first word to your last: Gemini reports
        # no onset of speech, so no quiet is counted in between.
        assert told[0] == {"type": "hearing"}
        assert [t["text"] for t in told if t["type"] == "said"] == ["Hello!"]
        # Each step as it runs, labelled as the thread's trail labels it.
        steps = [t.get("label") for t in told if t["type"] == "working"]
        assert steps == ["run_code: result = await report()"]
        # It ended the call: the page hangs up once the goodbye has played.
        assert {"type": "hang_up"} in told
        assert told[-1]["type"] == "saved"  # the thread reloads

    def test_the_page_cues_its_check_in_and_goodbye(
        self, client: TestClient, gemini: FakeRealtime, ended: threading.Event
    ) -> None:
        """No provider ends a call on quiet: the page counts it
        (call-state.js) and names a line; the assistant says the server's,
        and nothing the page made up."""
        with client.websocket_connect(SOCKET) as ws:
            ws.receive_json()
            ws.send_bytes(b"\x10\x20")  # the fake plays once it hears you
            ws.send_json({"type": "cue", "line": "check_in"})
            ws.send_json({"type": "cue", "line": "goodbye"})
            ws.send_json({"type": "cue", "line": "anything else"})
            ws.close()
            assert ended.wait(5)
        assert gemini.live.sent[1:] == [chat_live.CHECK_IN, chat_live.GOODBYE]

    def test_a_dropped_call_picks_up_where_it_stopped(
        self,
        client: TestClient,
        gemini: FakeRealtime,
        ended: threading.Event,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            realtime_calls, "resumed", lambda conversation: "How much is left?"
        )
        with client.websocket_connect(SOCKET) as ws:
            ws.receive_json()
            ws.send_bytes(b"\x10\x20")  # the fake plays once it hears you
            ws.close()
            assert ended.wait(5)
        (opening,) = gemini.live.sent
        assert "How much is left?" in opening

    def test_no_engine_on_offer_is_refused(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(chat_live, "_engine_now", _no_engine)
        with (
            pytest.raises(WebSocketDisconnect) as refused,
            client.websocket_connect(SOCKET) as ws,
        ):
            ws.receive_json()
        assert refused.value.code == 1008


class TestABoundCall:
    """A call is a turn: bound as the mount's pages are (``bind``), owned
    by the signed-in user (``get_optional_owner_user_id``) and let through
    by the mount's ``gate``."""

    def test_it_calls_as_the_mount_binds_it(
        self,
        app: FastAPI,  # the database, set up
        gemini: FakeRealtime,
        ended: threading.Event,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The conversation it starts is the bound user's, about the bound
        subject, answered by the bound mount's voice agent, and its tools
        run as them: each event seen in their turn."""
        during: list[tuple[str | None, int | None]] = []

        async def tell(ws: Any, event: Any) -> None:
            during.append((current_subject.get(), current_owner_user_id.get()))

        async def bound() -> ChatSurface:
            return replace(OVERSEER, user="7", subject="42", voice_agent_slug="voice")

        monkeypatch.setattr(chat_live, "_tell", tell)
        with _calls(replace(OVERSEER, bind=bound)).websocket_connect(SOCKET) as ws:
            ws.receive_json()
            ws.send_bytes(b"\x10\x20")  # the fake plays once it hears you
            ws.close()
            assert ended.wait(5)

        built = gemini.built
        meta = built["conversation"].metadata
        assert (meta["user_id"], meta["subject"]) == ("7", "42")
        assert (built["user_id"], built["owner_user_id"]) == ("7", 7)
        assert (built["subject"], built["agent_slug"]) == ("42", "voice")
        assert during and set(during) == {("42", 7)}

    def test_a_call_the_gate_refuses_never_opens(
        self, gemini: FakeRealtime, ends: tuple[queue.Queue[str], Any]
    ) -> None:
        """Over a plan's budget, a call is refused as a typed turn is, and
        never began: no end for the mount's hook."""
        heard, on_call_end = ends

        async def spent() -> str:
            return "Today's budget is spent."

        mount = replace(OVERSEER, gate=spent, on_call_end=on_call_end)
        with (
            pytest.raises(WebSocketDisconnect) as refused,
            _calls(mount).websocket_connect(SOCKET) as ws,
        ):
            ws.receive_json()
        assert (refused.value.code, refused.value.reason) == (
            1008,
            "Today's budget is spent.",
        )
        assert not hasattr(gemini, "built")
        assert heard.empty()

    def test_a_caller_the_mount_gives_no_controls_never_opens(
        self, gemini: FakeRealtime
    ) -> None:
        """No phone on their page is no call on the socket either: the
        socket refuses whom ``bind`` gives no operator controls."""

        async def customer() -> ChatSurface:
            return replace(OVERSEER, operator_controls=False)

        with (
            pytest.raises(WebSocketDisconnect) as refused,
            _calls(replace(OVERSEER, bind=customer)).websocket_connect(SOCKET) as ws,
        ):
            ws.receive_json()
        assert refused.value.code == 1008
        assert not hasattr(gemini, "built")

    def test_a_caller_the_mount_lets_call_without_controls_is_put_through(
        self,
        app: FastAPI,  # the database, set up
        gemini: FakeRealtime,
        ended: threading.Event,
    ) -> None:
        """Calls are their own switch: a mount may let in a caller it gives
        no controls (a signed-out visitor), on what the install calls with;
        the engine and what the call cost stay the operator's to see."""

        async def visitor() -> ChatSurface:
            return replace(OVERSEER, user="v1", operator_controls=False, calls=True)

        with _calls(replace(OVERSEER, bind=visitor)).websocket_connect(SOCKET) as ws:
            ready = ws.receive_json()
            ws.send_bytes(b"\x10\x20")  # the fake plays once it hears you
            _, told = _hear(ws, "saved")
            ws.close()
            assert ended.wait(5)
        assert gemini.built["user_id"] == "v1"
        assert ready["engine"] is None
        assert told[-1] == {"type": "saved"}


def test_a_call_acts_on_the_page_it_is_on(
    app: FastAPI,  # the database, set up
    gemini: FakeRealtime,
    ended: threading.Event,
) -> None:
    """A step she takes on the page reaches it at once, on a page the mount
    declares (the socket says which, as the stream's body does)."""
    gemini.live.events.insert(0, lambda: page_action("highlight", "docs"))
    mount = replace(OVERSEER, pages={"/": LANDING})
    with _calls(mount).websocket_connect(f"{SOCKET}?page=/") as ws:
        ws.send_bytes(b"\x10\x20")  # the fake plays once it hears you
        _, told = _hear(ws, "page")
        ws.close()
        assert ended.wait(5)
    assert told[-1] == {"type": "page", "action": "highlight", "target": "docs"}


class TestABoundedCall:
    """A mount may bound its calls (someone other than the operator pays
    for the minutes): a longest call, a check asked after each turn, and a
    hook once each call the gate let through is over, however it ended."""

    def test_it_wraps_up_then_ends_at_its_longest(
        self,
        app: FastAPI,  # the database, set up
        gemini: FakeRealtime,
        ends: tuple[queue.Queue[str], Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        heard, on_call_end = ends
        monkeypatch.setattr(chat_live, "WRAP_UP_SECONDS", 0.1)
        mount = replace(OVERSEER, longest_call=0.3, on_call_end=on_call_end)
        with _calls(mount).websocket_connect(SOCKET) as ws:
            _, told = _hear(ws, "ended")
            assert heard.get(timeout=5) == "limit"
        assert told[-1] == {"type": "ended", "reason": chat_live.TIME_UP}
        assert gemini.live.sent[-1] == chat_live.WRAP_UP  # she says it first

    def test_a_check_that_refuses_mid_call_ends_it_after_the_turn(
        self,
        app: FastAPI,  # the database, set up
        gemini: FakeRealtime,
        ends: tuple[queue.Queue[str], Any],
    ) -> None:
        heard, on_call_end = ends

        async def spent(bound: ChatSurface) -> str | None:
            return "Today's budget is spent."

        mount = replace(OVERSEER, call_check=spent, on_call_end=on_call_end)
        with _calls(mount).websocket_connect(SOCKET) as ws:
            ws.send_bytes(b"\x10\x20")  # the fake plays once it hears you
            _, told = _hear(ws, "ended")
            assert heard.get(timeout=5) == "refused"
        kinds = [t["type"] for t in told]
        assert kinds.index("saved") < kinds.index("ended")  # the turn is kept
        assert told[-1] == {"type": "ended", "reason": "Today's budget is spent."}

    def test_the_end_hook_runs_once_for_each_call_the_gate_let_through(
        self,
        app: FastAPI,  # the database, set up
        gemini: FakeRealtime,
        ends: tuple[queue.Queue[str], Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Hung up, or failed as it opened: each is one end. A call the gate
        refuses never began (``test_a_call_the_gate_refuses_never_opens``)."""
        heard, on_call_end = ends
        mount = replace(OVERSEER, on_call_end=on_call_end)
        with _calls(mount).websocket_connect(SOCKET) as ws:
            ws.receive()  # ready, or her voice
            ws.close()
            assert heard.get(timeout=5) == "page"

        monkeypatch.setattr(chat_live, "_engine_now", _no_engine)
        with (
            pytest.raises(WebSocketDisconnect),
            _calls(mount).websocket_connect(SOCKET) as ws,
        ):
            ws.receive_json()
        assert heard.get(timeout=5) == "error"
        assert heard.empty()


def test_a_call_into_a_conversation_does_not_meet_them_again() -> None:
    """A call into a conversation under way greets them as someone it
    knows; a first call greets; nothing to pick up is not a resume."""
    under_way = SimpleNamespace(messages=[SimpleNamespace(role="user", metadata={})])
    assert chat_live.opening(under_way) == chat_live.CONTINUING
    assert chat_live.opening(None) == chat_live.GREETING
    assert chat_live.opening(SimpleNamespace(messages=[])) == chat_live.GREETING


@pytest.mark.skipif(
    find_spec("app.services.auth") is None,
    reason="without auth a live call is open, as all of Overseer is",
)
def test_a_caller_who_is_not_signed_in_is_refused(app: FastAPI) -> None:
    """The socket's guard reads the session cookie: none, no call."""
    with (
        pytest.raises(WebSocketDisconnect) as refused,
        TestClient(app).websocket_connect(SOCKET) as ws,
    ):
        ws.receive_json()
    assert refused.value.code == 1008


def test_a_cue_that_is_not_one_says_nothing() -> None:
    """Whatever the page sends that is not a cue by name is no line: a
    malformed message does not end the call either."""
    assert chat_live._cue('{"line": "check_in"}') == chat_live.CHECK_IN
    assert chat_live._cue("not json") is None
    assert chat_live._cue('["check_in"]') is None
    assert chat_live._cue('{"line": "say something rude"}') is None


async def test_your_speech_is_relayed_from_its_first_sound() -> None:
    """OpenAI and xAI report speech onset before any transcript: a long
    sentence is you talking, not quiet the page counts toward a check-in."""
    from pydantic_ai.messages import (
        RealtimeInputSpeechEndEvent,
        RealtimeInputSpeechStartEvent,
    )

    from app.components.web_frontend.routes.partials import chat_live

    told: list[dict[str, object]] = []

    class Page:
        async def send_json(self, message: dict[str, object]) -> None:
            told.append(message)

    await chat_live._tell(Page(), RealtimeInputSpeechStartEvent())  # type: ignore[arg-type]
    await chat_live._tell(Page(), RealtimeInputSpeechEndEvent())  # type: ignore[arg-type]
    assert told == [{"type": "onset"}, {"type": "turn_end"}]


async def test_her_words_reach_the_page_as_she_says_them() -> None:
    """Her transcript so far, each time it grows, so a card on screen can
    follow what she names; your words are not hers to follow."""
    from pydantic_ai.messages import PartDeltaEvent, SpeechPartDelta

    from app.components.web_frontend.routes.partials import chat_live

    told: list[dict[str, object]] = []

    class Page:
        async def send_json(self, message: dict[str, object]) -> None:
            told.append(message)

    def delta(speaker: str, transcript: str | None) -> PartDeltaEvent:
        part = SpeechPartDelta(speaker=speaker, transcript=transcript)  # type: ignore[arg-type]
        return PartDeltaEvent(index=0, delta=part)  # type: ignore[arg-type]

    for event in (
        delta("assistant", "First the"),
        delta("assistant", "First the Server"),
        delta("assistant", None),  # audio only
        delta("user", "and you"),
    ):
        await chat_live._tell(Page(), event)  # type: ignore[arg-type]
    assert told == [
        {"type": "saying", "text": "First the"},
        {"type": "saying", "text": "First the Server"},
    ]
