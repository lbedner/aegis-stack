"""The Overseer AI page's Voice section, in two tabs. Design puts a voice
profile's voice together: who it sounds like narrows the voices, a premade
style and its dials say how, heard unsaved and saved. Models is one tight
table: what the active profile uses, every model and every voice, each a
row the page's filters narrow (``data-facets``), each voice playing on a
model that speaks it, Use putting one on the active profile. Below it, a
line said in a chosen voice and an audio file transcribed."""

from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qsl

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

pytest.importorskip("app.services.ai.domains.voice", reason="no voice in this stack")
# The page changes the voice profile, which only a database keeps.
pytest.importorskip(
    "app.services.ai.domains.voice.profiles", reason="no voice profiles"
)

from sqlmodel.ext.asyncio.session import AsyncSession  # noqa: E402

from app.components.web_frontend import overseer_ai_voice  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.services.ai.domains.voice import profiles  # noqa: E402
from app.services.ai.models.voice import VoiceProfile  # noqa: E402
from app.services.system.models import ComponentStatus  # noqa: E402
from tests._voice_catalog import keep_voice_settings, only_profile  # noqa: E402
from tests.web.dom import one, select, text, triggers  # noqa: E402
from tests.web.overseer import sign_in, status_with  # noqa: E402

PAGE = "/overseer/services/ai"
PARTIALS = "/partials/overseer/ai"
ROWS = "#ai-voice-rows tr"


@pytest.fixture
def client(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, async_db_session: AsyncSession
) -> TestClient:
    from app.core.db import get_async_db

    async def same_session() -> Any:
        yield async_db_session

    app.dependency_overrides[get_async_db] = same_session
    keep_voice_settings(monkeypatch)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    ai = ComponentStatus(name="ai", message="AI", metadata={"engine": "pydantic-ai"})
    sign_in(app, monkeypatch, status_with(services=[ai]))
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_library(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini's voice library is asked over the network: never here."""
    from app.services.ai.domains.voice import library

    monkeypatch.setattr(library, "TRIED", {"gemini"})
    monkeypatch.setattr(library, "KEPT", {})


@pytest.fixture
async def hers(async_db_session: AsyncSession) -> VoiceProfile:
    return await only_profile(async_db_session)


def _voice(client: TestClient, tab: str = "models", **query: str) -> str:
    """The Voice section's tab: Models (its table) unless asked for Profiles."""
    params = query | ({} if tab == "profiles" else {"tab": tab})
    response = client.get(f"{PAGE}/voice", params=params)
    assert response.status_code == 200, response.text
    return response.text


def _rows(html: str, kind: str) -> list[Any]:
    return select(html, f'{ROWS}[data-facet-kind="{kind}"]')


def _row(html: str, kind: str, name: str) -> Any:
    [found] = [r for r in _rows(html, kind) if name in text(r)]
    return found


async def test_what_is_in_use_leads_the_models(
    client: TestClient, hers: VoiceProfile
) -> None:
    html = _voice(client)
    used = _rows(html, "use")

    # Then calls, where a live engine is set up.
    assert [text(r.cssselect("td")[0]) for r in used] == ["Speaking", "Listening"]
    assert "tts-1" in text(used[0]) and "alloy" in text(used[0])
    assert "OPENAI_API_KEY" in text(used[0])  # named, since it is missing


async def test_every_model_and_voice_is_a_row_the_filters_narrow(
    client: TestClient, hers: VoiceProfile
) -> None:
    html = _voice(client)
    form = one(html, 'form[data-facets="#ai-voice-rows"]')

    for name in ("kind", "provider", "model"):
        assert select(form, f"[data-checklist] input[name={name}]"), name
    one(form, 'input[data-filter="#ai-voice-rows"]')
    kore = _row(html, "voice", "Kore")
    assert kore.get("data-facet-provider") == "gemini"
    assert "gemini-3.8-flash-tts" in kore.get("data-facet-model").split()
    _row(html, "tts", "gemini-3.8-flash-lite-tts")
    _row(html, "stt", "whisper-1")


async def test_each_voice_plays_on_a_model_that_speaks_it(
    client: TestClient, hers: VoiceProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tts-1 is in use, and does not speak marin: its row plays marin on
    one that does, as the preview route picks (``speaking_model``)."""
    for key in ("OPENAI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.setattr(settings, key, "set")
    html = _voice(client)

    for name in ("Marin", "Alloy", "Kore"):
        play = one(_row(html, "voice", name), "[data-speak]")
        assert play.get("data-speak").startswith("/api/v1/voice/preview/")
    assert "model=tts-1" in one(_row(html, "voice", "Alloy"), "[data-speak]").get(
        "data-speak"
    )


async def test_use_puts_a_voice_on_the_active_profile(
    client: TestClient, hers: VoiceProfile, async_db_session: AsyncSession
) -> None:
    """A Gemini voice brings Gemini and a model that speaks it, saved and
    in use at once."""
    response = client.post(
        f"{PARTIALS}/voice/use",
        data={"tts_voice": "Kore"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200, response.text
    await async_db_session.refresh(hers)
    assert (hers.tts_provider, hers.tts_model, hers.tts_voice) == (
        "gemini",
        "gemini-3.8-flash-tts",
        "Kore",
    )
    assert settings.TTS_VOICE == "Kore"
    assert "Kore" in text(_rows(_voice(client), "use")[0])


async def test_another_profile_is_made_the_one_in_use(
    client: TestClient, hers: VoiceProfile, async_db_session: AsyncSession
) -> None:
    plain = VoiceProfile(name="Plain", tts_model="gpt-4o-mini-tts", tts_voice="nova")
    async_db_session.add(plain)
    await async_db_session.commit()

    client.post(f"{PARTIALS}/voice/profile", data={"profile_id": plain.id})

    assert settings.TTS_VOICE == "nova"


async def test_every_profile_is_listed_to_hear_edit_or_use(
    client: TestClient, hers: VoiceProfile
) -> None:
    row = one(_voice(client, "profiles"), f"#voice-profile-{hers.id}")

    assert "Alloy" in text(row) and "In use" in text(row)
    assert one(row, "[data-voice-edit]").get("href").endswith(f"?profile={hers.id}")
    one(row, "[data-speak]")


async def test_a_new_profile_starts_from_the_one_in_use(
    client: TestClient, hers: VoiceProfile, async_db_session: AsyncSession
) -> None:
    response = client.post(f"{PARTIALS}/voice/profiles", data={"name": "Calls"})

    assert response.status_code == 200, response.text
    [made] = [
        p for p in await profiles.list_profiles(async_db_session) if p.name == "Calls"
    ]
    assert made.tts_voice == "alloy"


def _editor(client: TestClient, profile: VoiceProfile, **query: str) -> str:
    return _voice(client, "profiles", profile=str(profile.id), **query)


async def test_the_voice_step_opens_on_the_profiles_voice(
    client: TestClient, hers: VoiceProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only voices that can be heard are listed; a provider without its key
    is one line saying what it needs."""
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "set")
    html = _editor(client, hers)

    assert (
        one(html, "[data-voice-chosen] input[name=voice][checked]").get("value")
        == "alloy"
    )
    assert one(html, "[aria-current=step]").get("value") == "voice"
    assert "GOOGLE_API_KEY" in text(one(html, "[data-voice-locked]"))
    assert not html.count('data-voice-card="Kore"')


async def test_the_delivery_step_says_who_was_picked(
    client: TestClient, hers: VoiceProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "set")
    html = _editor(client, hers, go="delivery", step="voice", voice="marin")

    chosen = one(html, "[data-voice-chosen]")
    assert "Marin" in text(chosen) and "Warm" in text(chosen)
    one(chosen, "[data-speak]")


async def test_each_style_plays_with_the_fine_tuning_kept(
    client: TestClient, hers: VoiceProfile
) -> None:
    """A style's play is that style as it would be picked: its dials, and
    the accent, speed and anything extra already chosen."""
    html = _editor(
        client,
        hers,
        step="delivery",
        voice="marin",
        accent="british",
        speed="1.2",
        was_style="",
    )

    played = one(html, '[data-voice-style="calm"] [data-speak]').get("data-speak")
    query = dict(parse_qsl(played.split("?", 1)[1]))
    assert (query["style"], query["pace"], query["accent"], query["speed"]) == (
        "calm",
        "slow",
        "british",
        "1.2",
    )


async def test_a_style_just_picked_sets_the_dials_and_each_style_plays(
    client: TestClient, hers: VoiceProfile
) -> None:
    html = _editor(
        client, hers, step="delivery", voice="alloy", style="calm", was_style=""
    )

    assert one(html, "input[name=pace][value=slow]").get("checked") is not None
    calm = one(html, '[data-voice-style="calm"] [data-speak]')
    assert calm.get("data-speak").startswith("/api/v1/voice/design/preview?")
    one(html, "input[type=hidden][name=voice][value=alloy]")  # carried


async def test_the_review_says_what_is_sent_and_hears_it_unsaved(
    client: TestClient, hers: VoiceProfile
) -> None:
    html = _editor(
        client,
        hers,
        go="review",
        step="delivery",
        voice="marin",
        style="calm",
        was_style="calm",
    )

    assert text(one(html, "[data-voice-instructions]")).startswith("Voice Affect: Calm")
    listen = one(html, "form[data-voice-design] [data-speak]")
    assert listen.get("data-speak") == "/api/v1/voice/design/preview"
    assert listen.get("data-speak-form") is not None
    one(html, "input[type=hidden][name=voice][value=marin]")


async def test_save_puts_the_design_on_the_profile(
    client: TestClient, hers: VoiceProfile, async_db_session: AsyncSession
) -> None:
    form = {
        "profile": str(hers.id),
        "voice": "marin",
        "style": "support",
        "was_style": "support",
        "pace": "slow",
        "energy": "low",
        "emotion": "warm",
        "accent": "british",
        "speed": "1.1",
        "extra": "Say Aegis as EE-jis.",
    }

    response = client.post(f"{PARTIALS}/voice/design", data=form)

    assert response.status_code == 200, response.text
    await async_db_session.refresh(hers)
    assert (hers.tts_voice, hers.tts_model) == ("marin", "gpt-realtime-2.1-mini")
    assert hers.tts_delivery["accent"] == "british"
    assert hers.tts_instructions.endswith("Say Aegis as EE-jis.")
    assert settings.TTS_INSTRUCTIONS == hers.tts_instructions


def test_an_upload_is_transcribed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def transcribe(audio: Any) -> Any:
        return SimpleNamespace(text="hello from the file", language="en", duration=1.2)

    monkeypatch.setattr(overseer_ai_voice, "transcribe", transcribe)
    response = client.post(
        f"{PARTIALS}/voice/transcribe",
        files={"audio": ("clip.wav", b"RIFF....", "audio/wav")},
    )
    assert response.status_code == 200, response.text
    assert "hello from the file" in text(one(response.text, "#ai-voice-transcript"))


def test_a_refused_upload_is_the_toast(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    async def transcribe(audio: Any) -> Any:
        raise HTTPException(status_code=400, detail="Unsupported audio format: txt")

    monkeypatch.setattr(overseer_ai_voice, "transcribe", transcribe)
    response = client.post(
        f"{PARTIALS}/voice/transcribe",
        files={"audio": ("notes.txt", b"hi", "text/plain")},
    )
    toast = triggers(response)["toast"]
    assert toast["tone"] == "error" and "Unsupported audio format" in toast["text"]


async def test_a_provider_without_its_key_says_so_instead_of_playing(
    client: TestClient, hers: VoiceProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no GOOGLE_API_KEY, a Gemini voice cannot speak: offered, a Use
    would leave the stack with no voice at all. It says what it needs."""
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    kore = _row(_voice(client), "voice", "Kore")

    assert not kore.cssselect("[data-speak], [data-voice-use]")
    assert "GOOGLE_API_KEY missing" in text(kore)


async def test_the_voice_step_offers_the_models_that_speak_it(
    client: TestClient, hers: VoiceProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "set")
    html = _editor(client, hers)

    models = [m.get("value") for m in select(html, "input[name=model]")]
    assert "tts-1" in models and "gpt-4o-mini-tts" in models
    assert one(html, "input[name=model][checked]").get("value") == "tts-1"


async def test_delivery_says_the_model_and_when_it_ignores_the_choices(
    client: TestClient, hers: VoiceProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tts-1 follows no delivery instructions: the styles would do nothing,
    and the step says so before anything is picked."""
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "set")
    html = _editor(
        client, hers, go="delivery", step="voice", voice="alloy", model="tts-1"
    )

    assert "tts-1" in text(one(html, "[data-voice-chosen]"))
    one(html, "[data-voice-ignores]")
    one(html, "input[type=hidden][name=model][value=tts-1]")  # carried


async def test_fine_tune_offers_an_accent_only_where_the_model_steers_it(
    client: TestClient, hers: VoiceProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "set")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "set")
    openai = _editor(
        client,
        hers,
        go="delivery",
        step="voice",
        voice="marin",
        model="gpt-4o-mini-tts",
    )
    gemini = _editor(
        client,
        hers,
        go="delivery",
        step="voice",
        voice="Kore",
        model="gemini-3.8-flash-tts",
    )

    chips = "input[name=accent]:not([type=hidden])"
    assert select(openai, chips)
    assert not select(gemini, chips)  # the saved accent rides along hidden
    assert "comes with the voice" in text(one(gemini, "[data-voice-accent-note]"))


async def test_fine_tune_stays_open_as_the_form_redraws(
    client: TestClient, hers: VoiceProfile
) -> None:
    """Every pick redraws the form: Fine-tune is a fold, so the page keeps
    it as the person left it instead of shutting it each time."""
    page = _editor(client, hers, go="delivery", step="voice", voice="marin")

    assert 'data-fold="voice-fine-tune"' in page


async def test_speed_is_offered_only_where_the_model_takes_one(
    client: TestClient, hers: VoiceProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "set")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "set")
    openai = _editor(
        client,
        hers,
        go="delivery",
        step="voice",
        voice="marin",
        model="gpt-realtime-2.1-mini",
    )
    gemini = _editor(
        client,
        hers,
        go="delivery",
        step="voice",
        voice="Kore",
        model="gemini-3.8-flash-tts",
    )

    assert 'type="range" name="speed"' in openai and 'max="1.5"' in openai
    assert 'type="range" name="speed"' not in gemini
    assert 'type="hidden" name="speed"' in gemini  # the saved speed rides along


async def test_editing_opens_fine_tune_on_what_was_tuned(
    client: TestClient, hers: VoiceProfile, async_db_session: AsyncSession
) -> None:
    """A profile opened to edit shows everything it was saved with: its
    Fine-tune picks are not hidden in a closed fold."""
    from app.services.ai.domains.voice.delivery import styled

    async def fine_tune(delivery: dict[str, Any]) -> Any:
        hers.tts_voice, hers.tts_model = "marin", "gpt-realtime-2.1-mini"
        hers.tts_delivery = delivery
        async_db_session.add(hers)
        await async_db_session.commit()
        html = _editor(client, hers, go="delivery")
        return one(html, 'details[data-fold="voice-fine-tune"]')

    calm = styled("support").model_dump()
    assert (await fine_tune(calm | {"pace": "brisk", "accent": "british"})).get(
        "open"
    ) is not None
    assert (await fine_tune(calm | {"extra": "Say Aegis as EE-jis."})).get(
        "open"
    ) is not None
    assert (await fine_tune(calm)).get("open") is None


def _cards(html: str) -> list[str]:
    return [c.get("data-voice-card") for c in select(html, "[data-voice-card]")]


def _ticked(html: str, name: str) -> list[str]:
    return [i.get("value") for i in select(html, f"input[name={name}][checked]")]


@pytest.fixture
def heard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both providers' voices can be heard."""
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "set")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "set")


async def test_the_voice_step_opens_on_who_the_voice_is(
    client: TestClient, hers: VoiceProfile, heard: None, async_db_session: AsyncSession
) -> None:
    """Opened, the chosen voice is pinned above the search, which is for
    voices like it: its provider and accent."""
    hers.tts_voice, hers.tts_model = "marin", "gpt-realtime-2.1-mini"
    async_db_session.add(hers)
    await async_db_session.commit()

    html = _editor(client, hers)

    assert "Marin" in text(one(html, "[data-voice-chosen]"))
    assert "marin" not in _cards(html)  # pinned, not listed again
    assert _ticked(html, "provider") == ["openai"]
    assert _ticked(html, "accent_of") == ["General American"]
    assert not _ticked(html, "gender") and not _ticked(html, "family")
    assert {"cedar", "alloy"} <= set(_cards(html))


async def test_the_filters_narrow_and_a_cleared_one_stays_cleared(
    client: TestClient, hers: VoiceProfile, heard: None
) -> None:
    men = _editor(client, hers, filtered="1", provider="openai", gender="male")
    every = _editor(client, hers, filtered="1")  # every filter cleared

    assert "onyx" in _cards(men) and "marin" not in _cards(men)
    assert {"marin", "Kore"} <= set(_cards(every))
    assert not _ticked(every, "gender")


async def test_accents_are_grouped_by_language_and_a_language_takes_them_all(
    client: TestClient, hers: VoiceProfile, heard: None
) -> None:
    """OpenAI's voices speak two accents; a language ticked takes every
    accent of it."""
    openai = _editor(client, hers, filtered="1", provider="openai")
    english = _editor(client, hers, filtered="1", provider="openai", language="English")
    british = _editor(
        client, hers, filtered="1", provider="openai", accent_of="British"
    )

    options = select(
        openai,
        "[data-checklist] input[name=language], [data-checklist] input[name=accent_of]",
    )
    assert [(o.get("name"), o.get("value")) for o in options] == [
        ("language", "English"),
        ("accent_of", "British"),
        ("accent_of", "General American"),
    ]
    assert {"fable", "marin"} <= set(_cards(english))
    assert _cards(british) == ["fable"]


async def test_the_library_is_one_search_away(
    client: TestClient, hers: VoiceProfile, heard: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gemini's library runs to thousands: searched and filtered like any
    voice, the first few listed and how many more there are said."""
    from app.services.ai.domains.voice import finder, library
    from app.services.ai.domains.voice.models import VoiceInfo

    amelia = VoiceInfo(
        id="voice_en_gb_amelia",
        name="Amelia",
        provider_id="gemini",
        model_ids=["gemini-3.8-flash-tts"],
        description="Soft, calm voice.",
        gender="female",
        tone="Soft",
        accent="Glasgow English",
    )
    monkeypatch.setattr(library, "KEPT", {amelia.id: amelia})
    monkeypatch.setattr(finder, "LIMIT", 5)

    glasgow = _editor(client, hers, filtered="1", accent_of="Glasgow English")
    searched = _editor(client, hers, filtered="1", q="amelia")
    gemini = _editor(client, hers, filtered="1", provider="gemini")

    assert _cards(glasgow) == _cards(searched) == ["voice_en_gb_amelia"]
    assert len(_cards(gemini)) == 5
    assert "The first 5 of 31" in text(one(gemini, "[data-voice-more]"))


async def test_a_search_that_matches_nothing_says_so(
    client: TestClient, hers: VoiceProfile, heard: None
) -> None:
    """The chosen voice stays pinned, so the list going empty is said, not
    left looking as if nothing happened."""
    html = _editor(client, hers, filtered="1", q="nobody-sounds-like-this")

    assert one(html, "[data-voice-chosen]") and not _cards(html)
    assert "clear a filter" in text(one(html, "[data-voice-none]"))


async def test_each_voice_shows_its_providers_mark(
    client: TestClient, hers: VoiceProfile, heard: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every voice wears its provider's logo, the catalog's mark the
    Providers page shows (Gemini's is Google's); one without a mark shows
    its initial."""
    from app.services.ai.domains.voice import design

    async def marks(db: Any, orgs: Any) -> dict[str, str]:
        return {"openai": "iVBORw0KGgo="}  # Google's not held

    monkeypatch.setattr(design, "org_icons", marks)
    html = _editor(client, hers, filtered="1", provider=["openai", "gemini"])

    marin = one(html, '[data-voice-card="marin"] img')
    assert marin.get("src").endswith("/icons/openai")
    assert not select(html, '[data-voice-card="Kore"] img')
    chosen = one(html, "[data-voice-chosen] img")  # Alloy's, OpenAI
    assert chosen.get("src").endswith("/icons/openai")
