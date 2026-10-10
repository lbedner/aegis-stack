"""``aegis add`` / ``add-service`` next steps: a component or service that
brings Python dependencies is not importable until the image is rebuilt,
so the steps say to rebuild first (#1523: the app crashed on a missing
``fastmcp`` after ``aegis add mcp``)."""

import pytest

from aegis.constants import Messages


def test_the_steps_say_to_rebuild_when_it_brings_dependencies(
    capsys: pytest.CaptureFixture[str],
) -> None:
    Messages.print_next_steps(rebuild=True)

    out = capsys.readouterr().out
    assert "make rebuild" in out
    assert out.index("make rebuild") < out.index("make check")


def test_nothing_to_rebuild_says_nothing_about_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    Messages.print_next_steps()

    assert "make rebuild" not in capsys.readouterr().out
