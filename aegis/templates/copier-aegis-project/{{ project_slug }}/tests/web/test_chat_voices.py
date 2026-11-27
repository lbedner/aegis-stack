"""The voice, switched and tuned from the chat surface.

The composer carries a voice chip beside the model chip; it opens the one
dialog, which picks what a call runs on (the call setup), lists the voice
profiles with a preview each, switches the active one, makes a new one from
the active, and renames one. What changes applies to the next thing said,
with no restart; picking a model never changes the voice. Tested on the Overseer's
mount; every mount gets the same routes under its own path.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.web_frontend import chat_calls
from app.components.web_frontend.overseer_ai_chat import OVERSEER
from app.components.web_frontend.routes.partials import chat_voices
from app.core import speech_server
from app.core.config import settings
from app.services.ai.domains.voice import call_setup, profiles
from app.services.ai.models.voice import CallSetup, VoiceProfile
from tests._speech_server import PARAKEET
from tests._voice_catalog import keep_voice_settings, no_voices
from tests.web.dom import none, one, oob, select, text, triggers
from tests.web.overseer import AI, on_session, sign_in, status_with

VOICES = f"{OVERSEER.path}/voices"
# A realtime model a live call can run on.
LIVE = "gemini-3.8-live"
# A local chat model, which a call runs on as a cascade.
LOCAL = "qwen3.8:27b"
# A cloud chat model that calls tools, which a call runs on as a cascade too.
CLOUD = "claude-sonnet-5"


@pytest.fixture
def client(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, async_db_session: AsyncSession
) -> TestClient:
    """Signed in to the Overseer, on the test's own session: the routes and
    the assertions read one database."""
    on_session(app, async_db_session)
    sign_in(app, monkeypatch, status_with(services=[AI]))
    return TestClient(app)


@pytest.fixture
def hx(client: TestClient) -> TestClient:
    client.headers["HX-Request"] = "true"
    return client


@pytest.fixture(autouse=True)
def _restore_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Switching a profile writes the running settings; each test puts
    them back."""
    keep_voice_settings(monkeypatch)


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The realtime models a call can reach, and what calls run on: the
    last of these picks."""
    from app.components.web_frontend import chat_models as models

    picked: list[str] = []
    titles = {
        LIVE: "Gemini Live",
        "gpt-realtime-2.1": "GPT Realtime 2.1",
        LOCAL: "Qwen 3.8 27B",
    }

    async def catalog(mode: str | None = "chat") -> list[dict[str, Any]]:
        realtime = [
            {"model_id": LIVE, "title": "Gemini Live", "vendor": "google"},
            {
                "model_id": "gpt-realtime-2.1",
                "title": "GPT Realtime 2.1",
                "vendor": "openai",
                "input_price": 4.0,
                "output_price": 16.0,
            },
            # A dated snapshot of the one above: one row with it.
            {
                "model_id": "gpt-realtime-2.1-2026-08-28",
                "title": "GPT Realtime 2.1 2026 08 28",
                "vendor": "openai",
            },
        ]
        chat = [
            {
                "model_id": LOCAL,
                "title": "Qwen 3.8 27B",
                "vendor": "llamacpp",
                "supports_tools": True,
            },
            {
                "model_id": "tiny:1b",
                "title": "Tiny",
                "vendor": "llamacpp",
                "supports_tools": False,
            },
            {"model_id": "gpt-5.5", "title": "GPT-5.5", "vendor": "openai"},
            {
                "model_id": CLOUD,
                "title": "Claude Sonnet 5",
                "vendor": "anthropic",
                "supports_tools": True,
            },
        ]
        every = [{**m, "mode": "realtime"} for m in realtime] + [
            {**m, "mode": "chat"} for m in chat
        ]
        every.append(
            {
                "model_id": "nomic",
                "title": "Nomic",
                "vendor": "llamacpp",
                "mode": "embedding",
            }
        )
        return [m for m in every if mode in (None, m["mode"])]

    async def calling(db: Any) -> Any:
        return (
            SimpleNamespace(model_id=picked[-1], title=titles[picked[-1]])
            if picked
            else None
        )

    async def use_for_calls(model_id: str) -> str | None:
        if model_id not in titles:
            return f"A live call cannot run on {model_id}."
        picked.append(model_id)
        return None

    async def icons(listed: list[dict[str, Any]]) -> dict[str, str]:
        return {}

    monkeypatch.setattr(models, "catalog", catalog)
    monkeypatch.setattr(models, "calling_model", calling)
    monkeypatch.setattr(models, "use_for_calls", use_for_calls)
    monkeypatch.setattr(models, "vendor_icons", icons)
    return picked


# What the call setup is in these tests: OpenAI hears and speaks.
SETUP = {
    "stt_provider": "openai_whisper",
    "stt_model": "gpt-transcribe",
    "tts_provider": "openai",
    "tts_model": "gpt-4o-mini-tts-2025-03-20",
}


@pytest.fixture
async def voices(async_db_session: AsyncSession) -> dict[str, VoiceProfile]:
    """Marin (in use, styled) and Nova, on a call setup that speaks on
    OpenAI, applied to the running settings as the app's startup does."""
    await no_voices(async_db_session)
    setup = CallSetup(**SETUP)
    marin = VoiceProfile(
        name="Marin",
        is_active=True,
        voices={"openai": "marin"},
        tts_speed=1.2,
        tts_instructions="Voice Affect: Warm.",
    )
    nova = VoiceProfile(name="Nova, plain", voices={"openai": "nova"})
    async_db_session.add_all([setup, marin, nova])
    await async_db_session.commit()
    await async_db_session.refresh(marin)
    await async_db_session.refresh(nova)
    service = SimpleNamespace(_stt_service=None, _tts_service=None)
    profiles.apply(marin, settings, service, setup)
    return {"marin": marin, "nova": nova}


async def _setup(session: AsyncSession) -> CallSetup:
    setup = await profiles.call_setup(session)
    assert setup is not None
    await session.refresh(setup)
    return setup


class TestTheChip:
    def test_the_composer_loads_it(self, client: TestClient) -> None:
        page = client.get("/overseer/services/ai/chat").text
        loader = one(page, "#chat-composer #chat-voice")
        assert loader.get("hx-get") == f"{VOICES}/chip"
        # It sits inside the composer form, whose hx-target is the thread:
        # htmx inherits that, and would replace the whole conversation. A
        # loader names its own target.
        assert loader.get("hx-target") == "this"

    def test_it_names_the_active_voice_and_opens_the_dialog(
        self, hx: TestClient, voices: dict[str, VoiceProfile]
    ) -> None:
        chip = one(hx.get(f"{VOICES}/chip").text, "button#chat-voice")
        assert text(chip) == "Voice: Marin"
        assert chip.get("hx-get") == VOICES

    def test_with_a_live_engine_it_names_what_calls_run_on(
        self, hx: TestClient, voices: dict[str, VoiceProfile], calls: list[str]
    ) -> None:
        calls.append(LIVE)
        chip = one(hx.get(f"{VOICES}/chip").text, "button#chat-voice")
        assert text(chip) == "Calls: Gemini Live"


class TestCalls:
    """What a live call runs on, picked with the voice it speaks in, laid
    out as the parts a call is made of: one model that hears and speaks,
    or hear, think and speak (``chat_calls``)."""

    def test_one_model_lists_the_realtime_models_the_one_in_use_first(
        self, hx: TestClient, voices: dict[str, VoiceProfile], calls: list[str]
    ) -> None:
        calls.append("gpt-realtime-2.1")
        html = hx.get(chat_calls.address(VOICES, chat_calls.ONE, chat_calls.ONE)).text

        assert one(html, "[data-calls]").get("data-call-mode") == chat_calls.ONE
        rows = select(html, "[data-call-model]")
        assert [r.get("data-call-model") for r in rows] == ["gpt-realtime-2.1", LIVE]
        current = one(html, "[data-call-model][aria-current=true]")
        assert current.get("data-call-model") == "gpt-realtime-2.1"
        (part,) = select(html, "[data-call-part]")
        assert text(one(part, "[data-name]")) == "GPT Realtime 2.1"
        assert one(html, "[data-call-summary]") is not None

    # Two requests (the dialog, then what it opens), each reading once:
    # the test takes 2 on purpose, so 3 would be one read too many.
    @pytest.mark.queryspy(threshold=3)
    def test_the_dialog_shows_the_pick_and_opens_its_list_on_a_click(
        self, hx: TestClient, voices: dict[str, VoiceProfile], calls: list[str]
    ) -> None:
        """What calls run on is one card: its list of every model opens
        from it, and closes again from it."""
        calls.append("gpt-realtime-2.1")
        html = hx.get(VOICES).text

        (part,) = select(html, "[data-call-part]")
        assert text(one(part, "[data-name]")) == "GPT Realtime 2.1"
        assert not select(html, "[data-call-model]")
        opens = chat_calls.address(VOICES, chat_calls.ONE, chat_calls.ONE)
        assert part.get("hx-get") == opens
        (opened,) = select(hx.get(opens).text, "[data-call-part]")
        assert opened.get("hx-get") == chat_calls.address(VOICES, chat_calls.ONE)

    @pytest.mark.parametrize(
        ("model", "line"),
        [
            # OpenAI's realtime model takes her voice, style and speed.
            ("gpt-realtime-2.1", "On GPT Realtime 2.1: Marin · her style · 1.2×"),
            # Gemini takes her style; she has no Gemini voice, and it has
            # no speed to set.
            (LIVE, "On Gemini Live: Marin has no Gemini voice yet · her style"),
        ],
    )
    def test_speaks_as_says_what_of_her_the_call_takes(
        self,
        hx: TestClient,
        voices: dict[str, VoiceProfile],
        calls: list[str],
        model: str,
        line: str,
    ) -> None:
        calls.append(model)
        speaks = one(hx.get(VOICES).text, "[data-speaks-as]")

        assert text(one(speaks, "[data-name]")) == "Marin"
        assert text(one(speaks, "[data-speaking]")) == line
        assert one(speaks, "button[data-speak]").get("data-speak") == (
            f"{VOICES}/{voices['marin'].id}/preview"
        )

    def test_speaks_as_switches_to_another_voice(
        self, hx: TestClient, voices: dict[str, VoiceProfile], calls: list[str]
    ) -> None:
        calls.append("gpt-realtime-2.1")
        speaks = one(hx.get(VOICES).text, "[data-speaks-as]")

        picks = [
            (text(b), b.get("hx-post")) for b in select(speaks, "[data-voice-pick]")
        ]
        assert picks == [("Nova, plain", f"{VOICES}/{voices['nova'].id}/active")]

    def test_a_chain_shows_what_hears_thinks_and_speaks(
        self, hx: TestClient, voices: dict[str, VoiceProfile], calls: list[str]
    ) -> None:
        """A chat model that calls tools, local or cloud, runs between the
        active voice's STT and TTS: each part named, the models' list below,
        the summary adding them up. A model that does not say it calls
        tools and one that does not chat are not offered."""
        calls.append(LOCAL)
        html = hx.get(
            chat_calls.address(VOICES, chat_calls.CHAIN, chat_calls.THINKS)
        ).text

        assert one(html, "[data-calls]").get("data-call-mode") == chat_calls.CHAIN
        parts = {
            p.get("data-call-part"): text(one(p, "[data-name]"))
            for p in select(html, "[data-call-part]")
        }
        assert parts == {
            chat_calls.HEARS: "gpt-transcribe",
            chat_calls.THINKS: "Qwen 3.8 27B",
            chat_calls.SPEAKS: "gpt-4o-mini-tts-2025-03-20 · Marin",
        }
        opened = one(html, "[data-call-part][aria-current=true]")
        assert opened.get("data-call-part") == chat_calls.THINKS
        rows = [r.get("data-call-model") for r in select(html, "[data-call-model]")]
        assert rows == [LOCAL, CLOUD]
        assert chat_calls.LOCAL["label"] in text(
            one(html, f'[data-call-model="{LOCAL}"]')
        )
        assert chat_calls.CLOUD["label"] in text(
            one(html, f'[data-call-model="{CLOUD}"]')
        )
        assert "in the cloud" in text(one(html, "[data-call-summary]"))
        speaking = text(one(html, "[data-speaks-as] [data-speaking]"))
        assert speaking == "On OpenAI: Marin · her style · 1.2×"

    @pytest.mark.parametrize(
        ("query", "listed"), [("claude", [CLOUD]), ("nothing like it", [])]
    )
    def test_a_list_is_searched_in_its_own_box(
        self,
        hx: TestClient,
        voices: dict[str, VoiceProfile],
        calls: list[str],
        query: str,
        listed: list[str],
    ) -> None:
        """Thinks lists every vendor's tool callers: the box narrows it,
        keeping the mode and part it searches, and swaps only the list."""
        calls.append(LOCAL)
        where = {"mode": chat_calls.CHAIN, "slot": chat_calls.THINKS}
        html = hx.get(VOICES, params={**where, "q": query}).text

        box = one(html, "[data-calls] form[hx-select]")
        kept = {
            i.get("name"): i.get("value") for i in select(box, "input[type=hidden]")
        }
        assert kept == where
        assert box.get("hx-select") == "#call-list"
        assert one(box, "input[name=q]").get("value") == query
        rows = select(html, "#call-list [data-call-model]")
        assert [r.get("data-call-model") for r in rows] == listed
        if not listed:
            assert text(one(html, "#call-list")) == chat_calls.NO_MATCH

    def test_switching_to_a_chain_with_nothing_local_picked_asks_for_one(
        self, hx: TestClient, voices: dict[str, VoiceProfile], calls: list[str]
    ) -> None:
        calls.append(LIVE)
        html = hx.get(chat_calls.address(VOICES, chat_calls.CHAIN)).text

        thinks = one(html, f'[data-call-part="{chat_calls.THINKS}"]')
        assert text(one(thinks, "[data-name]")) == chat_calls.PICK
        assert not select(html, "[data-call-summary]")
        assert not select(html, "[data-call-model][aria-current=true]")

    def test_speaks_lists_the_speaking_models(
        self,
        hx: TestClient,
        voices: dict[str, VoiceProfile],
        calls: list[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Kokoro was running and nowhere to pick: Speaks listed the saved
        voices alone (2026-11-21)."""

        async def answering(url: str) -> bool:
            return True

        monkeypatch.setattr(settings, "SPEECH_BASE_URL", "http://server:5092/v1")
        monkeypatch.setattr(speech_server, "answers", answering)
        calls.append(LOCAL)
        url = chat_calls.address(VOICES, chat_calls.CHAIN, chat_calls.SPEAKS)
        html = hx.get(url).text

        kokoro = one(html, '[data-speak-model="kokoro"]')
        assert chat_calls.LOCAL["label"] in text(kokoro)
        current = one(html, "[data-speak-model][aria-current=true]")
        assert current.get("data-speak-model") == "gpt-4o-mini-tts-2025-03-20"
        assert not select(html, "[data-call-model]")

    @pytest.mark.parametrize("answers", [True, False])
    @pytest.mark.parametrize(
        ("part", "setting", "mark", "served"),
        [
            # Kokoro-FastAPI was picked while it was not running, and the
            # call ended on its first line (2026-11-21).
            (chat_calls.SPEAKS, "SPEECH_BASE_URL", "data-speak-model", "kokoro"),
            (
                chat_calls.HEARS,
                "HEARING_BASE_URL",
                "data-hear-model",
                PARAKEET,
            ),
        ],
    )
    def test_a_server_of_yours_is_offered_only_while_it_answers(
        self,
        hx: TestClient,
        voices: dict[str, VoiceProfile],
        calls: list[str],
        monkeypatch: pytest.MonkeyPatch,
        answers: bool,
        part: str,
        setting: str,
        mark: str,
        served: str,
    ) -> None:
        asked: list[str] = []

        async def answering(url: str) -> bool:
            asked.append(url)
            return answers

        monkeypatch.setattr(settings, setting, "http://server:5092/v1")
        monkeypatch.setattr(speech_server, "answers", answering)
        calls.append(LOCAL)
        html = hx.get(chat_calls.address(VOICES, chat_calls.CHAIN, part)).text

        rows = [r.get(mark) for r in select(html, f"[{mark}]")]
        assert (served in rows) is answers
        assert asked  # asked only for the list on show

    def test_a_speaking_model_says_what_runs_it(
        self,
        hx: TestClient,
        voices: dict[str, VoiceProfile],
        calls: list[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Kokoro-FastAPI's model is "Kokoro", as the in-app one is: a row
        named only that read as the in-app one (2026-11-25)."""

        async def answering(url: str) -> bool:
            return True

        monkeypatch.setattr(settings, "SPEECH_BASE_URL", "http://server:5092/v1")
        monkeypatch.setattr(speech_server, "answers", answering)
        calls.append(LOCAL)
        url = chat_calls.address(VOICES, chat_calls.CHAIN, chat_calls.SPEAKS)

        (row,) = select(hx.get(url).text, '[data-speak-model="kokoro"]')
        assert "Kokoro-FastAPI" in row.text_content()

    # Each step reads the call setup once (as each request does); the
    # test takes 2 on purpose, so 3 would be one read too many.
    @pytest.mark.queryspy(threshold=3)
    async def test_speaks_picks_the_setups_speaking_model_not_the_voice(
        self,
        hx: TestClient,
        voices: dict[str, VoiceProfile],
        calls: list[str],
        async_db_session: AsyncSession,
    ) -> None:
        """By its own provider; the voice stays hers. Marin has no Kokoro
        voice, so Kokoro speaks its own and the part says she has none
        there."""
        calls.append(LOCAL)
        response = hx.post(f"{VOICES}/speaks", data={"model_id": "kokoro"})

        setup = await _setup(async_db_session)
        assert (setup.tts_model, setup.tts_provider) == ("kokoro", "local_server")
        await async_db_session.refresh(voices["marin"])
        assert voices["marin"].voices == {"openai": "marin"}
        assert (settings.TTS_MODEL, settings.TTS_VOICE) == ("kokoro", None)
        speaks = one(response.text, f'[data-call-part="{chat_calls.SPEAKS}"]')
        assert text(one(speaks, "[data-name]")).startswith("Kokoro")
        assert chat_calls.LOCAL["label"] in text(speaks)
        assert call_setup.unvoiced(voices["marin"], "local_server") in text(speaks)

    def test_hears_lists_the_hearing_models_the_voices_marked(
        self, hx: TestClient, voices: dict[str, VoiceProfile], calls: list[str]
    ) -> None:
        calls.append(LOCAL)
        url = chat_calls.address(VOICES, chat_calls.CHAIN, chat_calls.HEARS)
        listed = hx.get(url).text

        heard = one(listed, "[data-hear-model][aria-current=true]")
        assert heard.get("data-hear-model") == "gpt-transcribe"

    @pytest.mark.parametrize("key", ["sk-test", None])
    def test_hears_offers_a_cloud_model_only_with_its_key(
        self,
        hx: TestClient,
        voices: dict[str, VoiceProfile],
        calls: list[str],
        monkeypatch: pytest.MonkeyPatch,
        key: str | None,
    ) -> None:
        """What can run is the voice overview's rule (``blocked``): with no
        key, a call on OpenAI's hearing fails on its first turn."""
        monkeypatch.setattr(settings, "OPENAI_API_KEY", key)
        calls.append(LOCAL)
        url = chat_calls.address(VOICES, chat_calls.CHAIN, chat_calls.HEARS)

        rows = [
            r.get("data-hear-model")
            for r in select(hx.get(url).text, "[data-hear-model]")
        ]
        assert ("gpt-transcribe" in rows) is bool(key)

    async def test_hears_picks_the_voices_hearing_model(
        self,
        hx: TestClient,
        voices: dict[str, VoiceProfile],
        calls: list[str],
        async_db_session: AsyncSession,
    ) -> None:
        """The call setup hears with it, by its own provider, at once: a
        call and the replies said in chat both."""
        calls.append(LOCAL)
        response = hx.post(f"{VOICES}/hears", data={"model_id": PARAKEET})

        setup = await _setup(async_db_session)
        assert (setup.stt_model, setup.stt_provider) == (PARAKEET, "hearing_server")
        assert settings.STT_MODEL == PARAKEET
        hears = one(response.text, f'[data-call-part="{chat_calls.HEARS}"]')
        assert text(one(hears, "[data-name]")) == "Parakeet TDT 0.6B v3 (speaches)"
        assert chat_calls.LOCAL["label"] in text(hears)

    async def test_a_pick_sets_what_calls_run_on_and_leaves_the_voice(
        self,
        hx: TestClient,
        voices: dict[str, VoiceProfile],
        calls: list[str],
        async_db_session: AsyncSession,
    ) -> None:
        before = voices["marin"].model_dump()
        response = hx.post(f"{VOICES}/calls", data={"model_id": "gpt-realtime-2.1"})

        assert calls == ["gpt-realtime-2.1"]
        await async_db_session.refresh(voices["marin"])
        assert voices["marin"].model_dump() == before
        _, siblings = oob(response.text)
        chip = [e for e in siblings if e.get("id") == "chat-voice"]
        assert [text(e) for e in chip] == ["Calls: GPT Realtime 2.1"]
        part = one(response.text, "[data-call-part] [data-name]")
        assert text(part) == "GPT Realtime 2.1"
        assert not select(response.text, "[data-call-model]")

    def test_a_model_billed_by_time_is_priced_by_the_minute(
        self,
        hx: TestClient,
        voices: dict[str, VoiceProfile],
        calls: list[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """As the summary adds a call up: a row billed by the second says
        what a minute costs, not a token price that was never the bill;
        one billed by its tokens keeps them. A dated snapshot is a version
        of its model, not a row of its own."""
        from app.components.web_frontend import chat_models as models

        listed = models.call_models

        async def timed() -> list[dict[str, Any]]:
            return [
                {**m, "per_second": 0.001} if m["model_id"] == LIVE else m
                for m in await listed()
            ]

        monkeypatch.setattr(models, "call_models", timed)
        html = hx.get(VOICES).text

        assert "$0.06 a minute" in text(one(html, f'[data-call-model="{LIVE}"]'))
        openai = text(one(html, '[data-call-model="gpt-realtime-2.1"]'))
        assert "$4 / $16" in openai and "2 versions" in openai
        assert not select(html, '[data-call-model="gpt-realtime-2.1-2026-08-28"]')

    def test_a_voice_with_none_for_the_models_vendor_says_so(
        self,
        hx: TestClient,
        voices: dict[str, VoiceProfile],
        calls: list[str],
    ) -> None:
        """Marin has no Gemini voice: the call would speak Gemini's own, and
        the dialog says so rather than naming a voice that is not hers."""
        calls.append(LIVE)
        html = hx.get(VOICES).text

        assert "Marin has no Gemini voice yet" in text(one(html, "[data-speaks-as]"))
        gemini = one(html, '[data-voice-card] [data-engine="gemini"]')
        assert "Not set" in text(gemini)
        # It opens her editor on Gemini's voices.
        assert one(gemini, "a[data-engine-pick]").get("href") == (
            f"/overseer/services/ai/voice?profile={voices['marin'].id}"
            "&filtered=1&provider=gemini"
        )

    def test_a_refused_pick_says_why(
        self, hx: TestClient, voices: dict[str, VoiceProfile], calls: list[str]
    ) -> None:
        response = hx.post(f"{VOICES}/calls", data={"model_id": "nope"})

        assert calls == [] and "nope" in triggers(response)["toast"]["text"]


class TestTheDialog:
    def test_its_two_panels_ask_for_the_widest_dialog(
        self, hx: TestClient, voices: dict[str, VoiceProfile]
    ) -> None:
        """The call (three stage cards side by side) beside the voice in
        use: any narrower and the stage cards cut their picks off."""
        assert one(hx.get(VOICES).text, "#voice-profiles").get("data-wider") is not None

    # Two requests (the dialog, then what it opens), each reading once:
    # the test takes 2 on purpose, so 3 would be one read too many.
    @pytest.mark.queryspy(threshold=3)
    def test_lists_every_voice_and_marks_the_active_one(
        self, hx: TestClient, voices: dict[str, VoiceProfile]
    ) -> None:
        manage = one(hx.get(VOICES).text, "[data-manage-voices]")
        assert manage.get("hx-get") == f"{VOICES}/manage"
        html = hx.get(f"{VOICES}/manage").text
        none(html, "html")
        rows = select(html, "[data-voice-profile]")
        assert [text(r.cssselect("[data-name]")[0]) for r in rows] == [
            "Marin",
            "Nova, plain",
        ]
        active = one(html, "[data-voice-profile][aria-current=true]")
        assert active.get("data-voice-profile") == str(voices["marin"].id)

    # Two requests (the dialog, then what it opens), each reading once:
    # the test takes 2 on purpose, so 3 would be one read too many.
    @pytest.mark.queryspy(threshold=3)
    def test_a_preview_shows_what_it_is_doing(
        self, hx: TestClient, voices: dict[str, VoiceProfile]
    ) -> None:
        """The same state visuals as the mic (one macro): loading, then an
        equalizer while it plays. A speaker never records."""
        for html in (
            hx.get(VOICES).text,
            hx.get(f"{VOICES}/manage").text,
            hx.get(f"{VOICES}/{voices['marin'].id}/edit").text,
        ):
            for button in select(html, "button[data-speak]"):
                assert button.get("data-state") == "idle"
                drawn = {
                    e.get("data-mic-visual")
                    for e in button.cssselect("[data-mic-visual]")
                }
                assert drawn == {"thinking", "speaking"}

    def test_every_voice_can_be_previewed(
        self, hx: TestClient, voices: dict[str, VoiceProfile]
    ) -> None:
        html = hx.get(f"{VOICES}/manage").text
        previews = [b.get("data-speak") for b in select(html, "button[data-speak]")]
        assert previews == [
            f"{VOICES}/{v.id}/preview" for v in (voices["marin"], voices["nova"])
        ]


class TestTheVoiceCard:
    """The voice in use, beside the call: her style and speed, her voice
    on each engine (each heard on its own), and the terms every voice
    says its way."""

    def test_it_shows_her_and_her_voice_on_each_engine(
        self, hx: TestClient, voices: dict[str, VoiceProfile]
    ) -> None:
        card = one(hx.get(VOICES).text, "[data-voice-card]")
        marin = voices["marin"].id

        assert text(one(card, "[data-name]")) == "Marin"
        assert (
            text(one(card, "[data-style]")) == "Style: Voice Affect: Warm. · Speed 1.2×"
        )
        openai = one(card, '[data-engine="openai"]')
        assert "Marin" in text(openai)
        assert one(openai, "button[data-speak]").get("data-speak") == (
            f"{VOICES}/{marin}/preview?engine=openai"
        )
        assert "Not set" in text(one(card, '[data-engine="gemini"]'))
        said = one(card, "[data-pronunciations]")
        assert said.get("hx-get") == f"{VOICES}/pronunciation"
        assert "Shared by every voice" in text(said)


class TestSwitching:
    async def test_the_next_thing_said_uses_it(
        self,
        hx: TestClient,
        voices: dict[str, VoiceProfile],
        async_db_session: AsyncSession,
    ) -> None:
        response = hx.post(f"{VOICES}/{voices['nova'].id}/active")

        assert response.status_code == 200
        assert settings.TTS_VOICE == "nova"  # applied to the running app
        # on the call setup's model: switching the voice does not move it
        assert settings.TTS_MODEL == "gpt-4o-mini-tts-2025-03-20"
        active = await profiles.active_profile(async_db_session)
        assert active is not None and active.name == "Nova, plain"
        primary, siblings = oob(response.text)
        chip = [e for e in siblings if e.get("id") == "chat-voice"]
        assert [text(e) for e in chip] == ["Voice: Nova, plain"]
        named = [
            text(e)
            for root in primary
            for e in root.cssselect("[data-voice-card] [data-name]")
        ]
        assert named == ["Nova, plain"]

    def test_a_missing_voice_is_a_404(
        self, hx: TestClient, voices: dict[str, VoiceProfile]
    ) -> None:
        assert hx.post(f"{VOICES}/999999/active").status_code == 404


class TestMaking:
    async def test_a_new_voice_starts_from_the_active_one(
        self,
        hx: TestClient,
        voices: dict[str, VoiceProfile],
        async_db_session: AsyncSession,
    ) -> None:
        response = hx.post(VOICES, data={"name": "Marin, faster"})

        assert response.status_code == 200
        made = next(
            p
            for p in await profiles.list_profiles(async_db_session)
            if p.name == "Marin, faster"
        )
        assert (made.voices, made.tts_speed, made.is_active) == (
            {"openai": "marin"},
            1.2,
            False,
        )
        # It opens straight into its own edit form.
        assert (
            one(response.text, "form[data-voice-form]").get("hx-post")
            == f"{VOICES}/{made.id}"
        )

    def test_a_taken_name_is_a_422_with_the_reason(
        self, hx: TestClient, voices: dict[str, VoiceProfile]
    ) -> None:
        response = hx.post(VOICES, data={"name": "Marin"})
        assert response.status_code == 422
        one(response.text, "[role=alert]")


class TestEditing:
    def test_the_form_names_her_voice_on_each_engine_and_opens_the_designer(
        self, hx: TestClient, voices: dict[str, VoiceProfile]
    ) -> None:
        """How she sounds (which voice on each engine, speed, delivery) is
        put together in the voice designer, one place; the form names it
        and opens the designer on this profile. How a call behaves is the
        call setup's, not here."""
        form = one(
            hx.get(f"{VOICES}/{voices['marin'].id}/edit").text, "form[data-voice-form]"
        )
        for column in ("stt_model", "reply", "working_sound", "live_engine"):
            assert not form.cssselect(f"[name={column}]"), column
        engines = {e.get("data-engine"): text(e) for e in select(form, "[data-engine]")}
        assert "Marin" in engines["openai"] and "Not set" in engines["gemini"]
        design = one(form, "a[data-voice-design]")
        assert (
            design.get("href")
            == f"/overseer/services/ai/voice?profile={voices['marin'].id}"
        )

    async def test_renaming_keeps_how_she_sounds(
        self,
        hx: TestClient,
        voices: dict[str, VoiceProfile],
        async_db_session: AsyncSession,
    ) -> None:
        marin = voices["marin"]
        response = hx.post(f"{VOICES}/{marin.id}", data={"name": "Marin, warm"})

        assert response.status_code == 200
        await async_db_session.refresh(marin)
        assert (marin.name, marin.voices) == ("Marin, warm", {"openai": "marin"})

    def test_a_voice_needs_a_name(
        self, hx: TestClient, voices: dict[str, VoiceProfile]
    ) -> None:
        response = hx.post(f"{VOICES}/{voices['marin'].id}", data={"name": " "})
        assert response.status_code == 422
        one(response.text, "form[data-voice-form] [role=alert]")


class TestCallSettings:
    """How every call behaves, whichever voice speaks: the call setup's
    form, opened from the dialog."""

    def test_the_dialog_opens_it(
        self, hx: TestClient, voices: dict[str, VoiceProfile]
    ) -> None:
        link = one(hx.get(VOICES).text, "[data-call-settings]")
        assert link.get("hx-get") == f"{VOICES}/setup"
        form = one(hx.get(f"{VOICES}/setup").text, "form[data-setup-form]")
        for column in ("stt_model", "reply", "working_sound"):
            one(form, f"select[name={column}]")
        assert [
            i.get("value") for i in form.cssselect("input[name=live_idle_seconds]")
        ] == ["30"]

    # Each step reads the call setup once (as each request does); the
    # test takes 2 on purpose, so 3 would be one read too many.
    @pytest.mark.queryspy(threshold=3)
    async def test_saving_applies_it(
        self,
        hx: TestClient,
        voices: dict[str, VoiceProfile],
        async_db_session: AsyncSession,
    ) -> None:
        response = hx.post(
            f"{VOICES}/setup",
            data=_setup_form(stt_model="whisper-1", live_idle_seconds="0"),
        )

        assert response.status_code == 200
        assert (settings.STT_MODEL, settings.VOICE_LIVE_IDLE_SECONDS) == (
            "whisper-1",
            0,  # never
        )
        assert (await _setup(async_db_session)).stt_model == "whisper-1"
        assert settings.TTS_VOICE == "marin"  # the voice untouched

    # Each step reads the call setup once (as each request does); the
    # test takes 2 on purpose, so 3 would be one read too many.
    @pytest.mark.queryspy(threshold=3)
    async def test_a_hearing_model_brings_its_provider(
        self,
        hx: TestClient,
        voices: dict[str, VoiceProfile],
        async_db_session: AsyncSession,
    ) -> None:
        """Any hearing model can be picked, and it is heard by its own
        provider: an OpenAI model kept beside Parakeet would be asked of
        the hearing server."""
        hx.post(f"{VOICES}/setup", data=_setup_form(stt_model=PARAKEET))

        assert (await _setup(async_db_session)).stt_provider == "hearing_server"

    @pytest.mark.parametrize(
        "change",
        [
            {"stt_model": "ghost"},
            {"live_idle_seconds": "-1"},
            {"live_idle_seconds": "601"},
            {"live_idle_seconds": "soon"},
        ],
    )
    def test_nonsense_is_a_422_that_keeps_the_form(
        self, hx: TestClient, voices: dict[str, VoiceProfile], change: dict[str, str]
    ) -> None:
        response = hx.post(f"{VOICES}/setup", data=_setup_form(**change))
        assert response.status_code == 422
        one(response.text, "form[data-setup-form] [role=alert]")


class TestPreviewing:
    def test_a_voice_the_provider_cannot_say_is_a_503(
        self,
        client: TestClient,
        voices: dict[str, VoiceProfile],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No key, no network: said plainly, as the speech API says it, not
        a crash."""

        class _Unreachable:
            def __init__(self, voice_settings: Any) -> None:
                pass

            async def synthesize(self, request: Any) -> Any:
                raise RuntimeError("the provider refused")

        monkeypatch.setattr(chat_voices, "TTSService", _Unreachable)
        response = client.get(f"{VOICES}/{voices['marin'].id}/preview")
        assert response.status_code == 503

    def test_a_preview_is_that_voice_not_the_active_one(
        self,
        client: TestClient,
        voices: dict[str, VoiceProfile],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        heard: list[Any] = []

        class _TTS:
            def __init__(self, voice_settings: Any) -> None:
                heard.append(voice_settings)

            async def synthesize(self, request: Any) -> Any:
                heard.append(request)
                return SimpleNamespace(audio=b"ID3", media_type="audio/mpeg")

        monkeypatch.setattr(chat_voices, "TTSService", _TTS)
        active = settings.TTS_VOICE
        response = client.get(f"{VOICES}/{voices['nova'].id}/preview")

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mpeg"
        preview_settings, request = heard
        assert (preview_settings.TTS_VOICE, preview_settings.TTS_MODEL) == (
            "nova",
            "gpt-4o-mini-tts-2025-03-20",
        )
        assert request.text == chat_voices.design.PREVIEW_TEXT
        assert settings.TTS_VOICE == active  # previewing does not switch

    async def test_a_preview_on_an_engine_is_her_voice_there(
        self,
        client: TestClient,
        voices: dict[str, VoiceProfile],
        monkeypatch: pytest.MonkeyPatch,
        async_db_session: AsyncSession,
    ) -> None:
        """Her Kokoro voice is heard on Kokoro, whatever the call setup
        speaks on."""
        heard: list[Any] = []

        class _TTS:
            def __init__(self, voice_settings: Any) -> None:
                heard.append(voice_settings)

            async def synthesize(self, request: Any) -> Any:
                return SimpleNamespace(audio=b"ID3", media_type="audio/mpeg")

        monkeypatch.setattr(chat_voices, "TTSService", _TTS)
        marin = voices["marin"]
        marin.voices = {**marin.voices, "local_server": "local_server:af_heart"}
        async_db_session.add(marin)
        await async_db_session.commit()

        url = f"{VOICES}/{marin.id}/preview?engine=local_server"
        assert client.get(url).status_code == 200
        (used,) = heard
        assert (used.TTS_PROVIDER, used.TTS_VOICE, used.TTS_MODEL) == (
            "local_server",
            "local_server:af_heart",
            "kokoro",
        )
        assert settings.TTS_PROVIDER == "openai"  # the setup untouched


def _setup_form(**changes: str) -> dict[str, str]:
    values = {
        "stt_model": SETUP["stt_model"],
        "reply": "live",
        "working_sound": "typing",
        "live_idle_seconds": "30",
    }
    values.update(changes)
    return values


# Each test saves, then reads the list back as the next turn does, so the
# same reads repeat by construction.
@pytest.mark.queryspy(allow_n_plus_one=True)
class TestPronunciation:
    """How terms are said, edited beside the voices: a row saved here is
    said its way on the next turn, by every voice, with no restart."""

    SAID = f"{VOICES}/pronunciation"

    @pytest.fixture(autouse=True)
    def _fresh_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.services.ai.domains.voice import spoken

        monkeypatch.setattr(spoken, "_saved", {})

    def _said(self, html: str) -> dict[str, str]:
        rows = select(html, "#voice-pronunciation tbody tr")
        return {text(row[0]): text(row[1]) for row in rows}

    def test_the_dialog_opens_on_the_list(
        self, hx: TestClient, voices: dict[str, VoiceProfile]
    ) -> None:
        opener = one(hx.get(VOICES).text, "[data-pronunciations]")
        assert opener.get("hx-get") == self.SAID
        assert self._said(hx.get(self.SAID).text)["Traefik"] == "traffic"

    async def test_a_saved_term_is_said_its_way_from_the_next_turn(
        self, hx: TestClient, async_db_session: AsyncSession
    ) -> None:
        from app.services.ai.domains.voice import pronunciations, spoken

        response = hx.post(self.SAID, data={"term": "Illiana", "say": "ill-ee-ah-na"})

        assert response.status_code == 200
        assert self._said(response.text)["Illiana"] == "ill-ee-ah-na"
        assert spoken.pronounced("Hi Illiana") == "Hi ill-ee-ah-na"
        rows = await pronunciations.saved(async_db_session)
        assert [(r.term, r.say) for r in rows] == [("Illiana", "ill-ee-ah-na")]

    async def test_saving_a_listed_term_again_changes_how_it_is_said(
        self, hx: TestClient, async_db_session: AsyncSession
    ) -> None:
        from app.services.ai.domains.voice import pronunciations, spoken

        hx.post(self.SAID, data={"term": "redis", "say": "ree-dis"})
        hx.post(self.SAID, data={"term": "Redis", "say": "red-dis"})

        assert spoken.pronounced("Redis") == "red-dis"
        assert len(await pronunciations.saved(async_db_session)) == 1

    async def test_removing_a_saved_term_brings_back_the_default(
        self, hx: TestClient, async_db_session: AsyncSession
    ) -> None:
        from app.services.ai.domains.voice import pronunciations, spoken

        hx.post(self.SAID, data={"term": "Traefik", "say": "tray-fik"})
        listed = hx.get(self.SAID).text
        (remove,) = select(listed, "#voice-pronunciation tbody button[hx-post]")
        assert remove.get("hx-vals") == '{"term": "Traefik"}'

        response = hx.post(f"{self.SAID}/delete", data={"term": "Traefik"})

        assert self._said(response.text)["Traefik"] == "traffic"
        assert await pronunciations.saved(async_db_session) == []
        assert spoken.pronounced("Traefik") == "traffic"

    def test_a_term_needs_how_it_is_said(self, hx: TestClient) -> None:
        response = hx.post(self.SAID, data={"term": "Illiana", "say": " "})

        assert response.status_code == 422
        assert "Illiana" not in self._said(response.text)

    async def test_the_app_starts_with_the_saved_list(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.ai.domains.voice import pronunciations, spoken

        await pronunciations.save(async_db_session, "Steward", "stew-ard")
        spoken.use_saved([])

        await profiles.load_active(async_db_session, settings, SimpleNamespace())

        assert spoken.pronounced("Steward") == "stew-ard"

    async def test_a_voice_outside_the_webserver_says_the_saved_list(
        self, async_db_session: AsyncSession
    ) -> None:
        """The meeting bot and the CLI read the voice themselves
        (``active_settings``); the saved list comes with it."""
        from app.services.ai.domains.voice import pronunciations, spoken

        await pronunciations.save(async_db_session, "Steward", "stew-ard")
        spoken.use_saved([])

        await profiles.active_settings(async_db_session, settings)

        assert spoken.pronounced("Steward") == "stew-ard"
