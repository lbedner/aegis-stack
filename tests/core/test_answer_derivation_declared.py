"""Every copier question must say how an existing project answers it.

``aegis update`` invents answers on the project's behalf: a question added
after a project was generated has no answer in its ``.copier-answers.yml``,
so copier renders with the template default — a guess, made silently, before
anything else runs. ``_detect_existing_features`` exists to close that gap,
but nothing has ever required a new question to be covered by it, so the gap
reopens every time someone adds one without thinking about existing
projects. It has already happened twice: ``include_insights`` after 0.6.10,
``ollama_mode`` in #1120.

Four ways a question can be accounted for, and a new one must pick one:

* an ``include_*`` flag whose spec declares a ``marker_path``, derived
  automatically from the registry;
* a key an explicit detector reads off the project (``DETECTED``);
* a default that is a Jinja expression over another answer, so getting the
  parent right gets this right too;
* an entry in ``NOT_INFERABLE`` (genuinely unanswerable from disk) or
  ``INFERENCE_DEBT`` (answerable, nobody has written the detector).

``INFERENCE_DEBT`` is a ratchet, like ``test_module_size_budget``'s BUDGET:
it records what is already unaccounted for so nothing gets worse, and it is
meant to shrink. Deleting an entry when its detector lands is the point.
"""

from pathlib import Path
from typing import Any

import yaml

from aegis.commands.update import DETECTED, INFERENCE_DEBT, NOT_INFERABLE
from aegis.constants import AnswerKeys
from aegis.core.components import COMPONENTS
from aegis.core.services import SERVICES

COPIER_YML = Path(__file__).parents[2] / "copier.yml"


def _questions() -> dict[str, dict[str, Any]]:
    loaded = yaml.safe_load(COPIER_YML.read_text())
    return {
        key: value
        for key, value in loaded.items()
        if not key.startswith("_") and isinstance(value, dict) and "type" in value
    }


def _marker_derived() -> set[str]:
    return {
        AnswerKeys.include_key(spec.name)
        for spec in (*SERVICES.values(), *COMPONENTS.values())
        if spec.marker_path
    }


def _default_derived(questions: dict[str, dict[str, Any]]) -> set[str]:
    """A Jinja default reads another answer, so the parent carries it."""
    return {
        key
        for key, value in questions.items()
        if isinstance(value.get("default"), str) and "{{" in value["default"]
    }


def test_every_question_declares_how_it_is_derived() -> None:
    questions = _questions()
    accounted = (
        _marker_derived()
        | _default_derived(questions)
        | set(DETECTED)
        | set(NOT_INFERABLE)
        | set(INFERENCE_DEBT)
    )
    undeclared = sorted(set(questions) - accounted)
    assert not undeclared, (
        "These copier questions say nothing about how an existing project "
        "answers them, so aegis update will take the template default and "
        f"say nothing: {undeclared}.\n"
        "Give each one a detector in _detect_existing_features (and name it "
        "in DETECTED), or an entry in NOT_INFERABLE / INFERENCE_DEBT in "
        "aegis/commands/update.py saying why not."
    )


def test_the_declarations_have_no_dead_entries() -> None:
    """A key that is no longer a question must not linger in a list."""
    questions = set(_questions())
    dead = sorted(
        (set(DETECTED) | set(NOT_INFERABLE) | set(INFERENCE_DEBT)) - questions
    )
    assert not dead, f"declared but no longer asked in copier.yml: {dead}"


def test_debt_and_impossible_do_not_overlap() -> None:
    """A key is either unanswerable or merely unanswered, never both."""
    both = sorted(set(NOT_INFERABLE) & set(INFERENCE_DEBT))
    assert not both, f"listed as both impossible and merely undone: {both}"


def test_detected_keys_are_actually_detected() -> None:
    """``DETECTED`` claims a detector exists; a stale claim is worse than none."""
    from aegis.commands.update import _detect_existing_features

    stale = sorted(key for key in DETECTED if key in NOT_INFERABLE)
    assert not stale, f"claimed detected and impossible at once: {stale}"
    # A project with nothing on disk detects nothing — the detector must not
    # invent an answer where there is no evidence.
    assert _detect_existing_features(Path("/nonexistent-project")) == {}
