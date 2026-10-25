"""The voice designer (``design``): a profile's voice picked by who it
sounds like and how it says things, heard unsaved, saved onto the profile."""

from types import SimpleNamespace

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.services.ai.domains.voice import design
from app.services.ai.domains.voice.delivery import compose, styled
from app.services.ai.models.voice import VoiceProfile
from tests._voice_catalog import keep_voice_settings, only_profile


@pytest.fixture
async def hers(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> VoiceProfile:
    keep_voice_settings(monkeypatch)
    return await only_profile(async_db_session)


async def test_the_designer_opens_on_the_profile(
    async_db_session: AsyncSession, hers: VoiceProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "set")  # its voices heard
    view = await design.design_view(async_db_session, hers.id, None)

    assert view.voice == "alloy" and view.profile.id == hers.id
    options = view.find.options
    assert {"female", "male", "neutral"} <= {o.value for o in options["gender"]}
    assert "warm" in {o.value for o in options["family"]} and "calm" in view.styles
    assert view.instructions == compose(view.delivery)


async def test_saving_puts_the_voice_and_its_delivery_on_the_profile(
    async_db_session: AsyncSession, hers: VoiceProfile
) -> None:
    """Marin is not spoken on tts-1: saving it moves the profile to a model
    that speaks it. The choices are kept, and the text they make is sent."""
    picked = design.Design(voice="marin", delivery=styled("calm"), speed=1.1)

    await design.save_design(
        async_db_session,
        hers.id,
        picked,
        SimpleNamespace(_stt_service=None, _tts_service=None),
    )
    await async_db_session.refresh(hers)

    assert (hers.tts_voice, hers.tts_model, hers.tts_speed) == (
        "marin",
        "gpt-realtime-2.1-mini",
        1.1,
    )
    assert hers.tts_instructions == compose(styled("calm"))
    assert hers.tts_delivery == styled("calm").model_dump()
    assert settings.TTS_VOICE == "marin"  # in use at once


def test_a_design_is_heard_unsaved_as_it_would_be_said() -> None:
    picked = design.Design(voice="Kore", delivery=styled("newsreader"), speed=1.0)

    heard = design.design_settings(picked, settings)

    assert (heard.TTS_PROVIDER, heard.TTS_VOICE) == ("gemini", "Kore")
    assert heard.TTS_INSTRUCTIONS == compose(styled("newsreader"))


def test_a_design_from_a_form_says_what_is_wrong() -> None:
    picked, errors = design.parse_design({"voice": "nobody", "pace": "glacial"})

    assert picked is None and len(errors) == 2


def test_a_style_just_picked_sets_the_dials_then_they_are_yours() -> None:
    form = {"voice": "alloy", "style": "calm", "pace": "brisk", "energy": "high"}

    picked, _ = design.parse_design(form | {"was_style": ""})
    kept, _ = design.parse_design(form | {"was_style": "calm"})

    assert picked is not None and picked.delivery.pace == "slow"
    assert kept is not None and kept.delivery.pace == "brisk"


def test_every_tone_falls_in_one_family() -> None:
    """The designer offers a handful of tone families, not every word a
    provider uses: a tone outside them could never be picked."""
    from app.services.ai.domains.voice.catalog import get_tts_voices
    from app.services.ai.domains.voice.traits import TONE_FAMILIES, family_of

    for voice in get_tts_voices():
        assert family_of(voice.tone or "") in TONE_FAMILIES, voice.id


async def test_a_provider_without_its_key_is_one_line_not_its_voices(
    async_db_session: AsyncSession, hers: VoiceProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "set")

    view = await design.design_view(async_db_session, hers.id, None, {"filtered": "1"})

    assert view.find.cards
    assert all(v.provider_name != "Gemini" for v in view.find.cards)
    [gemini] = view.locked
    assert (gemini.provider_name, gemini.voices, gemini.key) == (
        "Gemini",
        30,
        "GOOGLE_API_KEY",
    )


async def test_each_profile_is_summed_up(
    async_db_session: AsyncSession, hers: VoiceProfile
) -> None:
    await design.save_design(
        async_db_session,
        hers.id,
        design.Design(voice="marin", delivery=styled("calm"), speed=1.1),
        SimpleNamespace(_stt_service=None, _tts_service=None),
    )

    [summary] = await design.profile_summaries(async_db_session)

    assert (
        summary.name,
        summary.voice,
        summary.style,
        summary.speed,
        summary.active,
    ) == (
        "Hers",
        "Marin",
        "Calm and warm",
        1.1,
        True,
    )


async def test_the_voices_models_are_offered_each_saying_if_it_takes_instructions(
    async_db_session: AsyncSession, hers: VoiceProfile
) -> None:
    """Alloy is spoken on tts-1 (the profile's) and on gpt-4o-mini-tts:
    only the second follows delivery instructions."""
    view = await design.design_view(async_db_session, hers.id, None)

    assert view.model == "tts-1"
    takes = {m.id: m.instructions for m in view.models}
    assert takes["tts-1"] is False and takes["gpt-4o-mini-tts"] is True


async def test_a_model_picked_is_kept_and_one_that_cannot_speak_the_voice_is_not(
    async_db_session: AsyncSession, hers: VoiceProfile
) -> None:
    noop = SimpleNamespace(_stt_service=None, _tts_service=None)
    march = design.Design(
        voice="marin", model="gpt-4o-mini-tts-2025-03-20", delivery=styled("calm")
    )
    await design.save_design(async_db_session, hers.id, march, noop)
    await async_db_session.refresh(hers)
    assert hers.tts_model == "gpt-4o-mini-tts-2025-03-20"

    wrong = design.Design(voice="marin", model="tts-1", delivery=styled("calm"))
    await design.save_design(async_db_session, hers.id, wrong, noop)
    await async_db_session.refresh(hers)
    assert hers.tts_model == "gpt-realtime-2.1-mini"  # tts-1 does not speak marin


async def test_an_accent_the_model_cannot_steer_is_left_to_the_voice(
    async_db_session: AsyncSession, hers: VoiceProfile
) -> None:
    """Gemini takes the accent from the voice: asking it for one in the
    instructions would only be read as style, so it is not sent."""
    british = styled("calm").model_copy(update={"accent": "british"})
    picked = design.Design(voice="Kore", model="gemini-3.8-flash-tts", delivery=british)

    view = await design.design_view(async_db_session, hers.id, picked)

    assert view.steers_accent is False and "Accent" not in view.instructions
    assert "Accent" not in design.design_settings(picked, settings).TTS_INSTRUCTIONS


def test_a_design_refuses_a_voice_or_speed_there_is_not() -> None:
    """``Design`` checks itself, so the API's save (the Flet editor's,
    a body parsed straight into it) refuses what the form does."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="Pick a voice"):
        design.Design(voice="nobody", delivery=styled("calm"))
    with pytest.raises(ValidationError, match="Speed is a number"):
        design.Design(voice="marin", delivery=styled("calm"), speed=10)


async def test_the_speed_is_the_models_own(
    async_db_session: AsyncSession, hers: VoiceProfile
) -> None:
    """A speed past what the model takes is shown and saved as its most,
    not shown as one thing and spoken as another."""
    fast = design.Design(
        voice="marin", model="gpt-realtime-2.1-mini", delivery=styled("calm"), speed=2.0
    )

    view = await design.design_view(async_db_session, hers.id, fast)
    await design.save_design(
        async_db_session,
        hers.id,
        fast,
        SimpleNamespace(_stt_service=None, _tts_service=None),
    )
    await async_db_session.refresh(hers)

    assert view.speed == 1.5 and hers.tts_speed == 1.5
