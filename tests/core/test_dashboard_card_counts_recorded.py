"""Every card the framework ships has its field count recorded.

The generated ``test_dashboard_card_render.py`` grades each discovered card
against ``MINIMUM_FIELDS``, and skips a card it has no number for: a plugin
installs cards into the same package, and a plugin cannot edit a file the
framework owns and regenerates. That skip must never cover a first-party
card, so the "a new card cannot join without recording its number" rule
moves here, where the framework's own card set is known.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from aegis.core.component_files import get_template_path

PROJECT = Path(get_template_path()) / "{{ project_slug }}"
CARDS_DIR = PROJECT / "app" / "components" / "frontend" / "dashboard" / "cards"
RENDER_TEST = (
    PROJECT / "tests" / "components" / "frontend" / "test_dashboard_card_render.py"
)
CARD_CLASS = re.compile(r"^class (\w+Card)\b", re.M)


def _recorded() -> set[str]:
    tree = ast.parse(RENDER_TEST.read_text())
    table = next(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and getattr(node.target, "id", None) == "MINIMUM_FIELDS"
        and node.value is not None
    )
    return set(ast.literal_eval(table))


def _shipped() -> set[str]:
    names: set[str] = set()
    for path in CARDS_DIR.iterdir():
        if path.name.split(".")[0].endswith("_card"):
            names.update(CARD_CLASS.findall(path.read_text()))
    return names


def test_the_framework_ships_cards() -> None:
    assert _shipped(), f"no card classes found under {CARDS_DIR}"


def test_every_framework_card_has_a_recorded_count() -> None:
    missing = sorted(_shipped() - _recorded())
    assert not missing, (
        f"{missing} ship with the framework but are not in MINIMUM_FIELDS; "
        "the generated render test would skip them as if they were a plugin's."
    )
