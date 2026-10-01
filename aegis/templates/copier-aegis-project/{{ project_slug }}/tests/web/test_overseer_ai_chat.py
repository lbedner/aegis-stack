"""The Overseer's chat: one server-rendered surface, shown as the AI page's
Chat section and in the drawer beside every other Overseer page. The
server renders every bubble (history, a settled turn); chat.js and
voice.js only drive the live seconds, through data hooks the markup
carries."""

import asyncio
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_ai_chat
from app.services.ai.models import (
    AIProvider,
    Conversation,
    ConversationMessage,
    MessageRole,
)
from app.services.system.models import ComponentStatus
from tests.web.dom import one, select, text, triggers
from tests.web.overseer import sign_in, status_with

PAGE = "/overseer/services/ai"
CHAT = "/partials/overseer/ai/chat"
SCRIPTS = Path(overseer_ai_chat.__file__).parent / "static/js"

TRACE = [{"tool": "search_docs", "args": '{"q": "aegis"}', "result": "3 hits"}]
SHOT = {"key": "ab/cd.png", "media_type": "image/png", "name": "shot.png"}


def _conversation() -> Conversation:
    return Conversation(
        id="c1",
        title="Hello",
        provider=AIProvider.OLLAMA,
        model="llama3",
        metadata={"user_id": overseer_ai_chat.USER},
        messages=[
            ConversationMessage(
                id="m1",
                role=MessageRole.USER,
                content="What is Aegis?",
                metadata={"attachments": [SHOT]},
            ),
            ConversationMessage(
                id="m2",
                role=MessageRole.ASSISTANT,
                content="A **stack**.",
                metadata={"model": "llama3", "provider": "ollama", "tool_trace": TRACE},
            ),
        ],
    )


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    stored = _conversation()

    async def conversations() -> list[Conversation]:
        return [stored]

    async def find(conversation_id: str) -> Conversation | None:
        return stored if conversation_id == stored.id else None

    async def assistant_name() -> str:
        return "Illiana"

    async def provider_icons(providers: list[str]) -> dict[str, str]:
        return {p: f"/icons/{p}" for p in providers}

    monkeypatch.setattr(overseer_ai_chat, "conversations", conversations)
    monkeypatch.setattr(overseer_ai_chat, "find_conversation", find)
    monkeypatch.setattr(overseer_ai_chat, "assistant_name", assistant_name)
    monkeypatch.setattr(overseer_ai_chat, "provider_icons", provider_icons)
    ai = ComponentStatus(name="ai", message="AI", metadata={"engine": "pydantic-ai"})
    sign_in(app, monkeypatch, status_with(services=[ai]))
    return TestClient(app)


def _chat_page(client: TestClient) -> str:
    response = client.get(f"{PAGE}/chat")
    assert response.status_code == 200, response.text
    return response.text


def test_the_section_opens_on_the_latest_conversation(client: TestClient) -> None:
    html = _chat_page(client)
    bubbles = select(html, "#chat-thread [data-role]")
    assert [b.get("data-role") for b in bubbles] == ["user", "assistant"]
    assert "What is Aegis?" in text(bubbles[0])
    assert one(bubbles[1], "[data-body] strong") is not None  # markdown, server-side
    assert one(html, "#chat-conversation").get("value") == "c1"


def test_the_assistant_is_the_agent_by_name(client: TestClient) -> None:
    html = _chat_page(client)
    assert text(one(html, "[data-role=assistant] [data-assistant]")) == "Illiana"
    assert one(html, "#chat-composer textarea").get("placeholder") == "Message Illiana"


def test_the_header_carries_the_chat_verbs(client: TestClient) -> None:
    header = one(_chat_page(client), "#app-content header")
    assert "Ask Illiana anything" in text(header)
    assert select(header, "[hx-get$='/conversations/new']")
    assert select(header, "[hx-get$='/conversations']")


def test_one_surface_per_document(client: TestClient) -> None:
    """The page is the surface; the drawer frame beside it stays empty, so
    the ids the scripts look up by id answer for one element only."""
    html = _chat_page(client)
    assert len(select(html, "#chat")) == 1
    assert not select(html, "#chat-drawer-body > *")


def test_other_pages_carry_the_drawer_and_it_fetches_the_surface(
    client: TestClient,
) -> None:
    html = client.get(PAGE).text
    assert not select(html, "#chat")
    assert one(html, "#chat-fab") is not None
    drawer = client.get(f"{CHAT}/drawer").text
    assert len(select(drawer, "#chat")) == 1


def test_a_turn_appends_the_question_and_a_bubble_to_stream_into(
    client: TestClient,
) -> None:
    response = client.post(
        f"{CHAT}/turns",
        data={
            "message": " hi there ",
            "conversation_id": "c1",
            "attachment_names": ["a.png"],
        },
    )
    assert response.status_code == 200, response.text
    user = one(response.text, "[data-role=user]")
    assert text(one(user, "[data-text]")) == "hi there"
    assert "a.png" in text(one(user, "[data-attached]"))
    stream = one(response.text, "[data-stream]")
    assert stream.get("data-text") == "hi there"
    assert stream.get("data-conversation-id") == "c1"


def test_images_alone_are_a_turn_and_nothing_is_refused(client: TestClient) -> None:
    images = client.post(f"{CHAT}/turns", data={"attachment_names": ["a.png"]})
    assert one(images.text, "[data-stream]").get("data-text")
    assert client.post(f"{CHAT}/turns", data={"message": "  "}).status_code == 422


def test_a_settled_turn_is_the_servers_html(client: TestClient) -> None:
    html = client.get(f"{CHAT}/messages/c1/m2").text
    bubble = one(html, "[data-role=assistant]")
    assert bubble.get("data-message-id") == "m2"
    assert one(bubble, "[data-body] strong") is not None
    # The copy button carries the markdown source, not the rendered HTML.
    assert one(bubble, "button[data-copy]").get("data-copy") == "A **stack**."
    assert "llama3" in text(one(bubble, "[data-footer]"))
    assert one(bubble, "[data-model-icon] img").get("src") == "/icons/ollama"
    assert client.get(f"{CHAT}/messages/c1/nope").status_code == 404
    assert client.get(f"{CHAT}/messages/other/m2").status_code == 404


def test_a_reply_cut_off_at_the_limit_says_so(client: TestClient) -> None:
    """Ending mid-sentence reads as a broken app; the bubble says it was the
    token limit, and how many tokens that was."""
    stored = overseer_ai_chat.conversations
    message = asyncio.run(stored())[0].messages[1]
    message.metadata |= {"finish_reason": "length", "output_tokens": 1000}
    note = one(client.get(f"{CHAT}/messages/c1/m2").text, "[data-cut-off]")
    assert "1,000" in text(note)


def test_the_note_names_the_configured_limit(client: TestClient) -> None:
    """The agent's max_tokens is the limit; output tokens can fall short of it."""
    message = asyncio.run(overseer_ai_chat.conversations())[0].messages[1]
    message.metadata |= {
        "finish_reason": "length",
        "output_tokens": 998,
        "agent": {"slug": "assistant", "temperature": 0.7, "max_tokens": 1000},
    }
    note = one(client.get(f"{CHAT}/messages/c1/m2").text, "[data-cut-off]")
    assert "1,000-token" in text(note)


def test_a_finished_reply_has_no_cut_off_note(client: TestClient) -> None:
    assert not select(client.get(f"{CHAT}/messages/c1/m2").text, "[data-cut-off]")


AGENT_ROW = {
    "slug": "assistant",
    "name": "Illiana",
    "description": None,
    "category": None,
    "model_id": None,
    "temperature": 0.9,
    "max_tokens": 4000,
    "system_prompt": "You are Illiana.",
    "is_active": True,
}
SNAPSHOT = {"slug": "assistant", "temperature": 0.7, "max_tokens": 1000}


@pytest.fixture
def agent_drawer(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.components.web_frontend import overseer_ai_agents

    async def agent_row(db: Any, slug: str) -> dict[str, Any] | None:
        return AGENT_ROW if slug == "assistant" else None

    monkeypatch.setattr(overseer_ai_agents, "agent_row", agent_row)
    message = asyncio.run(overseer_ai_chat.conversations())[0].messages[1]
    message.metadata |= {"agent": SNAPSHOT}
    return client


def test_the_name_on_a_reply_opens_its_agent_in_the_drawer(client: TestClient) -> None:
    """The side drawer the Agents page edits in, not the centered modal."""
    name = one(client.get(f"{CHAT}/messages/c1/m2").text, "[data-assistant]")
    assert name.get("hx-get") == f"{CHAT}/messages/c1/m2/agent"
    assert name.get("hx-target") == "#drawer-body"


def test_the_agent_drawer_shows_what_the_reply_used_above_the_editor(
    agent_drawer: TestClient,
) -> None:
    html = agent_drawer.get(f"{CHAT}/messages/c1/m2/agent").text
    used = text(one(html, "#chat-reply-used"))
    assert "llama3" in used and "0.7" in used and "1,000" in used
    form = one(html, "form[data-agent]")
    assert one(form, "input[name=max_tokens]").get("value") == "4000"  # live value
    assert one(form, "input[name=stay]") is not None


def test_raise_max_tokens_lands_on_that_field(agent_drawer: TestClient) -> None:
    html = agent_drawer.get(f"{CHAT}/messages/c1/m2/agent?focus=max_tokens").text
    assert one(html, "input[name=max_tokens]").get("autofocus") is not None


def test_a_cut_off_reply_offers_raise_and_continue(client: TestClient) -> None:
    message = asyncio.run(overseer_ai_chat.conversations())[0].messages[1]
    message.metadata |= {"finish_reason": "length", "output_tokens": 1000}
    note = one(client.get(f"{CHAT}/messages/c1/m2").text, "[data-cut-off]")
    raise_button = one(note, "button[data-raise]")
    assert raise_button.get("hx-get") == f"{CHAT}/messages/c1/m2/agent?focus=max_tokens"
    assert raise_button.get("hx-target") == "#drawer-body"
    resume = one(note, "button[data-continue]")
    assert resume.get("hx-post") == f"{CHAT}/turns"
    assert '"conversation_id": "c1"' in resume.get("hx-vals")


def test_a_stored_image_shows_in_its_question(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    thumb = one(_chat_page(client), "[data-role=user] [data-attachments] img")
    assert thumb.get("src").startswith(f"{CHAT}/attachments/ab/cd.png")

    async def read(key: str) -> bytes | None:
        return b"PNG" if key == "ab/cd.png" else None

    monkeypatch.setattr(overseer_ai_chat, "read_attachment", read)
    image = client.get(thumb.get("src"))
    assert image.content == b"PNG" and image.headers["content-type"] == "image/png"
    assert client.get(f"{CHAT}/attachments/zz/none.png").status_code == 404


def test_a_tool_run_opens_with_what_it_did(client: TestClient) -> None:
    html = client.get(f"{CHAT}/messages/c1/m2").text
    row = one(html, "[data-trail] button")
    run = client.get(row.get("hx-get")).text
    assert "search_docs" in run and "3 hits" in run
    assert client.get(f"{CHAT}/messages/c1/m2/runs/9").status_code == 404


def test_history_loads_a_conversation_in_place(client: TestClient) -> None:
    history = client.get(f"{CHAT}/conversations").text
    pick = one(history, "[data-history] button")
    assert pick.get("hx-target") == "#chat-thread"
    loaded = client.get(pick.get("hx-get")).text
    assert "What is Aegis?" in loaded
    assert one(loaded, "#chat-conversation").get("hx-swap-oob") == "true"


def test_a_new_conversation_is_an_empty_thread(client: TestClient) -> None:
    html = client.get(f"{CHAT}/conversations/new").text
    assert not select(html, "[data-role]")
    assert one(html, "#chat-conversation").get("value") == ""


def test_the_hooks_the_scripts_read_are_the_ones_the_markup_emits(
    client: TestClient,
) -> None:
    """The scripts and the templates meet only at ids and data attributes;
    a rename on one side must fail here, not in a browser."""
    script = "".join((SCRIPTS / name).read_text() for name in ("chat.js", "voice.js"))
    ids = set(re.findall(r"getElementById\('([\w-]+)'\)", script))
    hooks = set(re.findall(r"\[(data-[\w-]+)[\]=]", script))
    pages = [
        _chat_page(client),
        client.post(f"{CHAT}/turns", data={"message": "hi"}).text,
    ]
    optional = {"dialog", "dialog-body"}
    if not overseer_ai_chat.HAS_VOICE:
        optional |= {"chat-mic", "chat-mic-states", "data-speak", "data-state"}
    for element_id in ids - optional:
        assert any(select(h, f"#{element_id}") for h in pages), element_id
    for hook in hooks - optional:
        assert any(select(h, f"[{hook}]") for h in pages), hook


class TestModelPicker:
    """The composer's model chip opens the picker: the models this install
    can call, grouped by vendor, the recently used leading, one search."""

    @pytest.fixture(autouse=True)
    def catalog(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        if not overseer_ai_chat.PERSISTED:
            pytest.skip("the picker reads the catalog")
        from app.components.web_frontend import overseer_ai_chat_models as models

        switched: list[str] = []

        async def catalog() -> list[dict[str, Any]]:
            return [
                {"model_id": "llama3", "title": "Llama 3", "vendor": "Ollama"},
                {"model_id": "claude-x", "title": "Claude X", "vendor": "Anthropic"},
            ]

        async def running() -> str:
            return switched[-1] if switched else "llama3"

        async def recent() -> list[str]:
            return ["claude-x"]

        async def switch(model_id: str) -> str | None:
            if model_id == "nope":
                return "OpenAI has no API key. Set OPENAI_API_KEY in .env first."
            switched.append(model_id)
            return None

        async def icons(vendors: list[str]) -> dict[str, str]:
            return {"Anthropic": "/icons/Anthropic"} if "Anthropic" in vendors else {}

        monkeypatch.setattr(models, "catalog", catalog)
        monkeypatch.setattr(models, "running_model", running)
        monkeypatch.setattr(models, "recent_ids", recent)
        monkeypatch.setattr(models, "switch", switch)
        monkeypatch.setattr(models, "vendor_icons", icons)
        return switched

    def test_the_chip_names_the_model_and_opens_the_picker(
        self, client: TestClient
    ) -> None:
        loader = one(_chat_page(client), "#chat-model")
        # Inside the composer, whose target is the thread: the loader must
        # name its own, or its swap replaces the whole thread.
        assert loader.get("hx-target") == "this"
        chip = one(client.get(loader.get("hx-get")).text, "#chat-model")
        assert text(one(chip, "[data-model]")) == "llama3"
        picker = client.get(chip.get("hx-get")).text
        assert one(picker, "#model-picker") is not None
        rows = [b.get("data-model-id") for b in select(picker, "[data-model-id]")]
        # The model in use and the recently used lead, then each vendor's group.
        assert rows[:2] == ["llama3", "claude-x"]
        assert sorted(rows[2:]) == ["claude-x", "llama3"]
        # Each vendor wears its mark from the icon route, not inlined bytes.
        header = one(picker, "details summary img")
        assert header.get("src") == "/icons/Anthropic"
        current = [b.get("data-model-id") for b in select(picker, "[aria-current]")]
        assert set(current) == {"llama3"} and len(current) == 2  # leading and grouped

    def test_a_search_narrows_to_one_flat_list(self, client: TestClient) -> None:
        picker = client.get(f"{CHAT}/models", params={"q": "claude"}).text
        assert [b.get("data-model-id") for b in select(picker, "[data-model-id]")] == [
            "claude-x"
        ]

    def test_a_pick_switches_and_updates_the_chip(
        self, client: TestClient, catalog: list[str]
    ) -> None:
        response = client.post(f"{CHAT}/models", data={"model_id": "claude-x"})
        assert catalog == ["claude-x"]
        chip = one(response.text, "#chat-model")
        assert chip.get("hx-swap-oob") == "true"
        assert text(one(chip, "[data-model]")) == "claude-x"

    def test_a_refused_pick_says_why(self, client: TestClient) -> None:
        response = client.post(f"{CHAT}/models", data={"model_id": "nope"})
        toast = triggers(response)["toast"]
        assert toast["tone"] == "error" and "OPENAI_API_KEY" in toast["text"]


class TestVoice:
    @pytest.fixture(autouse=True)
    def voice(self) -> None:
        if not overseer_ai_chat.HAS_VOICE:
            pytest.skip("no voice in this stack")

    def test_the_mic_transcribes_what_was_said(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.components.web_frontend import overseer_ai_voice

        async def transcribe(audio: Any) -> Any:
            return SimpleNamespace(text="  what is aegis  ")

        monkeypatch.setattr(overseer_ai_voice, "transcribe", transcribe)
        mic = one(_chat_page(client), "#chat-mic")
        response = client.post(
            mic.get("data-transcripts"),
            files={"audio": ("clip.webm", b"....", "audio/webm")},
        )
        assert response.json() == {"text": "what is aegis"}

    def test_nothing_heard_says_so(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.components.web_frontend import overseer_ai_voice

        async def transcribe(audio: Any) -> Any:
            return SimpleNamespace(text="  ")

        monkeypatch.setattr(overseer_ai_voice, "transcribe", transcribe)
        response = client.post(
            f"{CHAT}/speech/transcripts",
            files={"audio": ("clip.webm", b"....", "audio/webm")},
        )
        assert response.status_code == 422 and response.json()["error"]

    def test_sentences_and_answers_are_said_aloud(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        said: list[str] = []

        async def speak(text: str) -> bytes:
            said.append(text)
            return b"MP3"

        monkeypatch.setattr(overseer_ai_chat, "synthesize", speak)
        mic = one(_chat_page(client), "#chat-mic")
        sentence = client.get(mic.get("data-say"), params={"text": "Hello there."})
        assert sentence.content == b"MP3"
        answer = one(client.get(f"{CHAT}/messages/c1/m2").text, "[data-speak]")
        assert client.get(answer.get("data-speak")).content == b"MP3"
        assert said == ["Hello there.", "A stack."]
