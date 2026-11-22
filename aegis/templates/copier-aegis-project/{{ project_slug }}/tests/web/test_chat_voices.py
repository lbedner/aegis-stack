"""The voice, switched and tuned from the chat surface.

The composer carries a voice chip beside the model chip; it opens the one
dialog, which lists the voice profiles with a preview each, switches the
active one, makes a new one from the active, and edits one. What changes
applies to the next thing said, with no restart. Tested on the Overseer's
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
from app.core.config import settings
from app.services.ai.domains.voice import profiles
from app.services.ai.models.voice import VoiceProfile
from tests._voice_catalog import keep_voice_settings
from tests.web.dom import none, one, oob, select, text, triggers
from tests.web.overseer import AI, on_session, sign_in, status_with

VOICES = f"{OVERSEER.path}/voices"
# A realtime model a live call can run on.
LIVE = "gemini-3.8-live"
# A local chat model, which a call runs on as a cascade.
LOCAL = "qwen3.8:27b"


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


@pytest.fixture
async def voices(async_db_session: AsyncSession) -> dict[str, VoiceProfile]:
    for row in await profiles.list_profiles(async_db_session):
        await async_db_session.delete(row)
    await async_db_session.commit()
    marin = VoiceProfile(
        name="Marin",
        is_active=True,
        stt_model="gpt-transcribe",
        tts_model="gpt-4o-mini-tts-2025-03-20",
        tts_voice="marin",
        tts_speed=1.2,
        tts_instructions="Voice Affect: Warm.",
    )
    nova = VoiceProfile(
        name="Nova, plain", tts_model="gpt-4o-mini-tts", tts_voice="nova"
    )
    async_db_session.add_all([marin, nova])
    await async_db_session.commit()
    await async_db_session.refresh(marin)
    await async_db_session.refresh(nova)
    return {"marin": marin, "nova": nova}


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
        html = hx.get(VOICES).text

        assert one(html, "[data-calls]").get("data-call-mode") == chat_calls.ONE
        rows = select(html, "[data-call-model]")
        assert [r.get("data-call-model") for r in rows] == ["gpt-realtime-2.1", LIVE]
        current = one(html, "[data-call-model][aria-current=true]")
        assert current.get("data-call-model") == "gpt-realtime-2.1"
        (part,) = select(html, "[data-call-part]")
        assert text(one(part, "[data-name]")) == "GPT Realtime 2.1"
        # Marin is an OpenAI voice: the call speaks in it.
        assert "speaks as marin" in text(part)
        assert one(html, "[data-call-summary]") is not None
        # The voices stay in view: the replies said in chat use one.
        assert select(html, "[data-voice-profile]")

    def test_a_chain_shows_what_hears_thinks_and_speaks(
        self, hx: TestClient, voices: dict[str, VoiceProfile], calls: list[str]
    ) -> None:
        """A local model runs between the active voice's STT and TTS: each
        part named, the model's list below, the summary adding them up. A
        cloud chat model, a model that cannot call tools and one that does
        not chat are not offered."""
        calls.append(LOCAL)
        html = hx.get(VOICES).text

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
        assert rows == [LOCAL]
        assert chat_calls.TOOLS["label"] in text(
            one(html, f'[data-call-model="{LOCAL}"]')
        )
        assert "in the cloud" in text(one(html, "[data-call-summary]"))
        # Speaks is the voice: its list opens there, not under Thinks.
        assert not select(html, "[data-voice-profile]")

    def test_switching_to_a_chain_with_nothing_local_picked_asks_for_one(
        self, hx: TestClient, voices: dict[str, VoiceProfile], calls: list[str]
    ) -> None:
        calls.append(LIVE)
        html = hx.get(chat_calls.address(VOICES, chat_calls.CHAIN)).text

        thinks = one(html, f'[data-call-part="{chat_calls.THINKS}"]')
        assert text(one(thinks, "[data-name]")) == chat_calls.PICK
        assert not select(html, "[data-call-summary]")
        assert not select(html, "[data-call-model][aria-current=true]")

    def test_speaks_opens_the_voices(
        self, hx: TestClient, voices: dict[str, VoiceProfile], calls: list[str]
    ) -> None:
        calls.append(LOCAL)
        url = chat_calls.address(VOICES, chat_calls.CHAIN, chat_calls.SPEAKS)
        html = hx.get(url).text

        assert len(select(html, "[data-voice-profile]")) == 2
        assert not select(html, "[data-call-model]")

    def test_hears_lists_the_hearing_models_the_voices_marked(
        self, hx: TestClient, voices: dict[str, VoiceProfile], calls: list[str]
    ) -> None:
        calls.append(LOCAL)
        url = chat_calls.address(VOICES, chat_calls.CHAIN, chat_calls.HEARS)
        listed = hx.get(url).text

        heard = one(listed, "[data-hear-model][aria-current=true]")
        assert heard.get("data-hear-model") == "gpt-transcribe"

    async def test_hears_picks_the_voices_hearing_model(
        self,
        hx: TestClient,
        voices: dict[str, VoiceProfile],
        calls: list[str],
        async_db_session: AsyncSession,
    ) -> None:
        """The active voice hears with it, by its own provider, at once:
        a call and the replies said in chat both."""
        calls.append(LOCAL)
        response = hx.post(f"{VOICES}/hears", data={"model_id": "large-v3"})

        await async_db_session.refresh(voices["marin"])
        assert (voices["marin"].stt_model, voices["marin"].stt_provider) == (
            "large-v3",
            "faster_whisper",
        )
        assert settings.STT_MODEL == "large-v3"
        hears = one(response.text, f'[data-call-part="{chat_calls.HEARS}"]')
        assert text(one(hears, "[data-name]")) == "Large v3"
        assert chat_calls.LOCAL["label"] in text(hears)

    def test_a_pick_sets_what_calls_run_on(
        self, hx: TestClient, voices: dict[str, VoiceProfile], calls: list[str]
    ) -> None:
        response = hx.post(f"{VOICES}/calls", data={"model_id": "gpt-realtime-2.1"})

        assert calls == ["gpt-realtime-2.1"]
        _, siblings = oob(response.text)
        chip = [e for e in siblings if e.get("id") == "chat-voice"]
        assert [text(e) for e in chip] == ["Calls: GPT Realtime 2.1"]
        current = one(response.text, "[data-call-model][aria-current=true]")
        assert current.get("data-call-model") == "gpt-realtime-2.1"

    def test_a_refused_pick_says_why(
        self, hx: TestClient, voices: dict[str, VoiceProfile], calls: list[str]
    ) -> None:
        response = hx.post(f"{VOICES}/calls", data={"model_id": "nope"})

        assert calls == [] and "nope" in triggers(response)["toast"]["text"]


class TestTheDialog:
    def test_lists_every_voice_and_marks_the_active_one(
        self, hx: TestClient, voices: dict[str, VoiceProfile]
    ) -> None:
        html = hx.get(VOICES).text
        none(html, "html")
        rows = select(html, "[data-voice-profile]")
        assert [text(r.cssselect("[data-name]")[0]) for r in rows] == [
            "Marin",
            "Nova, plain",
        ]
        active = one(html, "[data-voice-profile][aria-current=true]")
        assert active.get("data-voice-profile") == str(voices["marin"].id)

    def test_a_preview_shows_what_it_is_doing(
        self, hx: TestClient, voices: dict[str, VoiceProfile]
    ) -> None:
        """The same state visuals as the mic (one macro): loading, then an
        equalizer while it plays. A speaker never records."""
        for html in (
            hx.get(VOICES).text,
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
        html = hx.get(VOICES).text
        previews = [b.get("data-speak") for b in select(html, "button[data-speak]")]
        assert previews == [
            f"{VOICES}/{v.id}/preview" for v in (voices["marin"], voices["nova"])
        ]


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
        assert settings.TTS_MODEL == "gpt-4o-mini-tts"
        active = await profiles.active_profile(async_db_session)
        assert active is not None and active.name == "Nova, plain"
        primary, siblings = oob(response.text)
        chip = [e for e in siblings if e.get("id") == "chat-voice"]
        assert [text(e) for e in chip] == ["Voice: Nova, plain"]
        current = [
            e
            for root in primary
            for e in root.cssselect("[data-voice-profile][aria-current=true]")
        ]
        assert [e.get("data-voice-profile") for e in current] == [
            str(voices["nova"].id)
        ]

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
        assert (made.tts_voice, made.tts_speed, made.is_active) == ("marin", 1.2, False)
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
    def test_the_form_holds_what_the_designer_does_not_and_opens_it(
        self, hx: TestClient, voices: dict[str, VoiceProfile]
    ) -> None:
        """The voice itself (which one, its model, speed and delivery) is
        put together in the voice designer, one place; the form keeps the
        rest and opens the designer on this profile."""
        form = one(
            hx.get(f"{VOICES}/{voices['marin'].id}/edit").text, "form[data-voice-form]"
        )
        for column in ("stt_model", "reply", "working_sound"):
            one(form, f"select[name={column}]")
        for column in ("tts_voice", "tts_model", "tts_speed", "tts_instructions"):
            assert not form.cssselect(f"[name={column}]"), column
        design = one(form, "a[data-voice-design]")
        assert (
            design.get("href")
            == f"/overseer/services/ai/voice?profile={voices['marin'].id}"
        )

    async def test_saving_the_active_voice_applies_it(
        self,
        hx: TestClient,
        voices: dict[str, VoiceProfile],
        async_db_session: AsyncSession,
    ) -> None:
        response = hx.post(
            f"{VOICES}/{voices['marin'].id}",
            data=_form(voices["marin"], stt_model="whisper-1"),
        )

        assert response.status_code == 200
        assert settings.STT_MODEL == "whisper-1"
        await async_db_session.refresh(voices["marin"])
        assert voices["marin"].stt_model == "whisper-1"

    async def test_a_hearing_model_brings_its_provider(
        self,
        hx: TestClient,
        voices: dict[str, VoiceProfile],
        async_db_session: AsyncSession,
    ) -> None:
        """Any hearing model can be picked, and it is heard by its own
        provider: an OpenAI model kept beside Parakeet would be asked of
        Parakeet."""
        hx.post(
            f"{VOICES}/{voices['marin'].id}",
            data=_form(voices["marin"], stt_model="nemo-parakeet-tdt-0.6b-v3"),
        )

        await async_db_session.refresh(voices["marin"])
        assert voices["marin"].stt_provider == "parakeet"

    def test_the_form_holds_the_live_dead_air_limit(
        self, hx: TestClient, voices: dict[str, VoiceProfile]
    ) -> None:
        form = one(
            hx.get(f"{VOICES}/{voices['marin'].id}/edit").text, "form[data-voice-form]"
        )
        assert [
            i.get("value") for i in form.cssselect("input[name=live_idle_seconds]")
        ] == ["30"]

    def test_the_live_dead_air_limit_is_saved_and_applied(
        self, hx: TestClient, voices: dict[str, VoiceProfile]
    ) -> None:
        response = hx.post(
            f"{VOICES}/{voices['marin'].id}",
            data=_form(voices["marin"], live_idle_seconds="0"),
        )
        assert response.status_code == 200
        assert settings.VOICE_LIVE_IDLE_SECONDS == 0  # 0: never

    async def test_saving_another_voice_leaves_the_active_one_alone(
        self, hx: TestClient, voices: dict[str, VoiceProfile]
    ) -> None:
        before = settings.STT_MODEL
        hx.post(
            f"{VOICES}/{voices['nova'].id}",
            data=_form(voices["nova"], stt_model="whisper-1"),
        )
        assert settings.STT_MODEL == before

    async def test_the_live_engine_is_picked_with_the_models_not_here(
        self,
        hx: TestClient,
        voices: dict[str, VoiceProfile],
        async_db_session: AsyncSession,
    ) -> None:
        """One place picks what a call runs on (the dialog's Calls list);
        the voice form neither offers it nor loses it on a save."""
        marin = voices["marin"]
        form = one(hx.get(f"{VOICES}/{marin.id}/edit").text, "form[data-voice-form]")
        assert form.cssselect("select[name=live_engine]") == []
        marin.live_engine = "gpt-realtime-2.1"
        async_db_session.add(marin)
        await async_db_session.commit()

        hx.post(f"{VOICES}/{marin.id}", data=_form(marin, tts_voice="coral"))

        await async_db_session.refresh(marin)
        assert marin.live_engine == "gpt-realtime-2.1"

    @pytest.mark.parametrize(
        "change",
        [
            {"stt_model": "ghost"},
            {"name": ""},
            {"live_idle_seconds": "-1"},
            {"live_idle_seconds": "601"},
            {"live_idle_seconds": "soon"},
        ],
    )
    def test_nonsense_is_a_422_that_keeps_the_form(
        self, hx: TestClient, voices: dict[str, VoiceProfile], change: dict[str, str]
    ) -> None:
        response = hx.post(
            f"{VOICES}/{voices['marin'].id}", data=_form(voices["marin"], **change)
        )
        assert response.status_code == 422
        one(response.text, "form[data-voice-form] [role=alert]")


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
            "gpt-4o-mini-tts",
        )
        assert request.text == chat_voices.design.PREVIEW_TEXT
        assert settings.TTS_VOICE == active  # previewing does not switch


def _form(profile: VoiceProfile, **changes: str) -> dict[str, str]:
    values = {
        "name": profile.name,
        "stt_model": profile.stt_model or "",
        "reply": profile.reply,
        "working_sound": profile.working_sound,
        "live_idle_seconds": str(profile.live_idle_seconds),
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
