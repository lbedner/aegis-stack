"""How a voice says things (``delivery``): premade choices composed into
the delivery instructions a speech model takes."""

import pytest

from app.services.ai.domains.voice.delivery import STYLES, Delivery, compose, styled


def test_a_style_fills_in_how_it_is_said() -> None:
    calm = styled("calm")

    assert (calm.pace, calm.energy, calm.emotion) == (
        STYLES["calm"].pace,
        STYLES["calm"].energy,
        STYLES["calm"].emotion,
    )


def test_the_choices_become_the_instructions_extra_last() -> None:
    said = compose(
        styled("calm").model_copy(
            update={"accent": "british", "extra": "Say Aegis as EE-jis."}
        )
    )

    lines = said.splitlines()
    assert lines[0].startswith("Voice Affect: ") and lines[1].startswith("Tone: ")
    assert any(line.startswith("Accent: ") for line in lines)
    assert said.endswith("Say Aegis as EE-jis.")


def test_without_a_style_only_the_dials_are_said() -> None:
    said = compose(Delivery(pace="brisk"))

    assert not said.startswith("Voice Affect")
    assert said.startswith("Pacing: ") and "Accent" not in said


def test_a_choice_not_on_offer_is_refused() -> None:
    with pytest.raises(ValueError):
        Delivery(pace="glacial")
