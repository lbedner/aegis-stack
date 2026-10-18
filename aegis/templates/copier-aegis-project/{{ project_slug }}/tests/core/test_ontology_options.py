"""What each part could be, beside what it is: its options from
``app/core/parts.py``, each with the choice this stack was generated with
(``.copier-answers.yml``)."""

from app.core import source_index
from app.core.ontology import parts
from app.core.ontology.model import PartOption


def _by_name(name: str, answers: dict[str, object]) -> dict[str, PartOption]:
    return {o.name: o for o in parts.options_of(name, answers)}


def test_each_option_says_its_choices_and_this_stacks() -> None:
    ai = _by_name("ai", {"ai_backend": "sqlite", "ai_providers": "ollama,anthropic"})
    assert ai["backend"].choices == ("memory", "sqlite", "postgres")
    assert ai["backend"].default == "memory"
    assert ai["backend"].chosen == "sqlite"
    assert ai["backend"].about["memory"]  # the guided setup's line for it
    assert ai["providers"].chosen == ("ollama", "anthropic")


def test_a_flag_is_on_or_off_and_an_unrecorded_choice_is_unknown() -> None:
    ai = _by_name("ai", {"ai_rag": True})
    assert ai["rag"].chosen is True
    assert ai["rag"].default is False  # a flag is off unless chosen
    assert ai["voice"].chosen is None  # no answer recorded: not known


def test_a_part_without_options_has_none() -> None:
    assert parts.options_of("backend", {}) == ()
    assert parts.options_of("not-a-part", {}) == ()


def test_the_part_node_carries_them() -> None:
    """Illiana's ontology answer for a part dumps its node: the options
    ride on it."""
    (node, *_) = parts.parts([], ["ai"], source_index.project())
    assert {o.name for o in node.options} >= {"framework", "backend", "providers"}
