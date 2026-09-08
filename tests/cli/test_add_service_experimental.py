"""``aegis add-service <experimental>`` warns once and carries on.

The warning is a line, not a prompt: ``-y`` semantics are unchanged and a
scripted install is not interrupted. The badge the listing and wizard show
comes from the same label, so the surfaces cannot disagree about the word.
"""

from __future__ import annotations

import pytest

from aegis.cli import brand
from aegis.commands.add_service import warn_experimental
from tests.cli.test_utils import strip_ansi_codes


def test_warns_once_per_experimental_service(
    capsys: pytest.CaptureFixture[str],
) -> None:
    warn_experimental(["finance"])
    out = strip_ansi_codes(capsys.readouterr().out)
    assert out.count("finance") == 1
    assert "experimental" in out


def test_silent_for_empty_list(capsys: pytest.CaptureFixture[str]) -> None:
    warn_experimental([])
    assert capsys.readouterr().out == ""


def test_badge_is_the_label_in_the_warning_colour() -> None:
    assert strip_ansi_codes(brand.experimental_badge()) == brand.experimental_label()
    assert brand.experimental_badge() != brand.experimental_label(), (
        "badge must carry the warning colour"
    )
