"""An answer key names a component or service, never one of its options."""

from aegis.constants import AnswerKeys


def test_options_never_reach_the_key() -> None:
    """``database[sqlite]`` is the database component with an option; a
    key that kept the bracket matched no copier question and was carried
    forward by every later update."""
    assert AnswerKeys.include_key("database[sqlite]") == "include_database"
    assert AnswerKeys.include_key("ai[pydantic-ai,sqlite,voice]") == "include_ai"


def test_a_plain_name_is_unchanged() -> None:
    assert AnswerKeys.include_key("scheduler") == "include_scheduler"
