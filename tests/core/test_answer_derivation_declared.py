"""A newly added copier question must be recoverable for existing projects.

``aegis update`` invents answers on the project's behalf. A question added
after a project was generated has no answer in its ``.copier-answers.yml``,
so copier renders with the template default — a guess, made silently, before
anything else runs. It has bitten twice: ``include_insights`` after 0.6.10,
``ollama_mode`` in #1120.

Only questions ADDED since a project could have been generated can be
missing, and git already records which those are — so this computes the
at-risk set from ``copier.yml`` at an older tag rather than storing a list
of it. A question in that set is accounted for when:

* its ``include_*`` flag has a spec with a ``marker_path``;
* an ``OptionSpec`` names it in ``answer_key``;
* its default is a Jinja expression over another answer, so the parent
  carries it;
* ``_detect_existing_features`` reads it off the project.

All four are derived. Nothing here is a hand-kept copy of what the code
already knows, which is the whole point: a list would drift, and the list
this replaced already had.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from aegis.commands.update import _detect_existing_features
from aegis.constants import AnswerKeys
from aegis.core.components import COMPONENTS
from aegis.core.services import SERVICES

REPO = Path(__file__).parents[2]
COPIER_YML = REPO / "copier.yml"
TEMPLATE = REPO / "aegis" / "templates" / "copier-aegis-project"
MINOR_TAG = re.compile(r"^v(\d+)\.(\d+)\.0$")

# How many minor versions back an update is expected to work from. Projects
# older than this are updated by hand, so a question added before then
# cannot be missing from any answers file this guard has to care about.
SUPPORTED_MINORS = 3


def _parse_questions(text: str) -> dict[str, dict[str, Any]]:
    loaded = yaml.safe_load(text) or {}
    return {
        key: value
        for key, value in loaded.items()
        if not key.startswith("_") and isinstance(value, dict) and "type" in value
    }


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout


def _anchor_tag() -> str:
    """The oldest release an update is expected to work from."""
    minors = sorted(
        {
            (int(m.group(1)), int(m.group(2)))
            for line in _git("tag").splitlines()
            if (m := MINOR_TAG.match(line.strip()))
        }
    )
    if len(minors) < SUPPORTED_MINORS:
        pytest.skip("not enough release history to compute the at-risk set")
    major, minor = minors[-SUPPORTED_MINORS]
    return f"v{major}.{minor}.0"


def _questions_added_since(tag: str) -> set[str]:
    old = _parse_questions(_git("show", f"{tag}:copier.yml"))
    return set(_parse_questions(COPIER_YML.read_text())) - set(old)


def _registry_derived() -> set[str]:
    """Answers the spec registry can already recover for a project."""
    specs = (*SERVICES.values(), *COMPONENTS.values())
    covered = {AnswerKeys.include_key(spec.name) for spec in specs if spec.marker_path}
    covered |= {
        option.answer_key
        for spec in specs
        for option in (spec.options or [])
        if option.answer_key
    }
    return covered


def _default_derived(questions: dict[str, dict[str, Any]]) -> set[str]:
    return {
        key
        for key, value in questions.items()
        if isinstance(value.get("default"), str) and "{{" in value["default"]
    }


def _detector_derived(tmp_path: Path) -> set[str]:
    """Keys ``_detect_existing_features`` produces, by running it.

    A fixture rather than a list: the detectors themselves say what they can
    recover. A detector added without a matching fixture shows up as an
    uncovered question, which is the right way to find out.
    """
    config = tmp_path / "app" / "core" / "config.py"
    config.parent.mkdir(parents=True)
    config.write_text(
        "class Settings:\n"
        "    FINANCE_PLAID: bool = True\n"
        "    FINANCE_SNAPTRADE: bool = True\n"
    )
    (tmp_path / ".env").write_text("OLLAMA_BASE_URL=http://ollama:11434\n")
    return set(_detect_existing_features(tmp_path))


def test_new_questions_are_recoverable_for_existing_projects(
    tmp_path: Path,
) -> None:
    anchor = _anchor_tag()
    at_risk = _questions_added_since(anchor)
    questions = _parse_questions(COPIER_YML.read_text())

    uncovered = at_risk - (
        _registry_derived() | _default_derived(questions) | _detector_derived(tmp_path)
    )
    assert not uncovered, (
        f"These questions were added since {anchor}, so a project generated "
        "before them has no answer and aegis update will take the template "
        f"default: {sorted(uncovered)}.\n"
        "Give each one a marker_path, an OptionSpec answer_key, or a "
        "detector in _detect_existing_features."
    )


def test_the_at_risk_set_is_actually_computed() -> None:
    """A guard that silently measures nothing passes forever."""
    assert _questions_added_since(_anchor_tag()), (
        "no questions added since the anchor — the computation is broken, "
        "or the anchor is wrong"
    )
