"""What an agent is doing, step by step: each tool call, heard by whoever is
watching, as a phrase a person reads."""

from app.core.steps import doing, heard, watching
from app.core.tools import register_tool, unregister_tool


def _look(text: str) -> str:
    return text


def test_a_tool_says_what_it_is_doing_where_it_declares_it() -> None:
    register_tool("look_up", _look, effect="read", doing="Looking it up")
    try:
        assert doing("look_up") == "Looking it up"
    finally:
        unregister_tool("look_up")


def test_a_script_is_what_its_first_comment_says() -> None:
    script = "# What depends on the cache\nprint(1)"

    assert doing("run_code", script) == "What depends on the cache"
    assert doing("run_code", "print(1)") == "Running a script"


def test_any_other_tool_is_its_name_made_readable() -> None:
    assert doing("bill_candidates") == "Bill candidates"


def test_a_step_is_heard_only_where_someone_is_watching() -> None:
    steps: list[str] = []

    heard("bill_candidates")
    with watching(lambda doing, *_: steps.append(doing)):
        heard("bill_candidates")
    heard("bill_candidates")

    assert steps == ["Bill candidates"]


def test_a_listener_inside_anothers_is_told_beside_it() -> None:
    """A chat turn's trail listens inside the meeting bot that runs it:
    both hear each step, the call as well as its phrase."""
    outer: list[tuple[object, ...]] = []
    inner: list[tuple[object, ...]] = []

    with watching(lambda *step: outer.append(step)):
        with watching(lambda *step: inner.append(step)):
            heard("bill_candidates", {"months": 3})

    assert outer == inner == [("Bill candidates", "bill_candidates", {"months": 3})]
