"""Illiana's review threads (``scripts/illiana_threads.py``)."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

SCRIPT = Path(__file__).parents[2] / "scripts/illiana_threads.py"
STORE = "templates/{{ project_slug }}/app/services/notes/store.py.jinja"


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("illiana_threads", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


threads = _script()


def _spot(line: int | None, key: str, blocking: bool = True) -> Any:
    return threads.Spot(
        path=STORE,
        line=line,
        check="service.takes-session",
        title="Takes its session",
        why="A second session waits.",
        action="Open none.",
        blocking=blocking,
        key=key,
    )


def test_the_places_are_read_as_the_check_wrote_them(tmp_path: Path) -> None:
    found = tmp_path / "found.json"
    place = _spot(2, "k")._asdict() | {"subject": "service:notes"}
    found.write_text(json.dumps({"found": [place]}))

    assert threads.spots(found) == [_spot(2, "k")]


def test_no_file_is_nothing_to_do_never_everything_fixed(tmp_path: Path) -> None:
    """The check crashed: no thread may be resolved as if fixed."""
    assert threads.spots(tmp_path / "found.json") is None


def test_only_lines_the_change_shows_take_a_comment() -> None:
    """GitHub takes a review comment on a line of the diff's new side: an
    added line or one shown around it, never a removed one."""
    patch = "@@ -1,3 +1,3 @@\n a\n-b\n+c\n d\n@@ -10,0 +10,1 @@\n+e"

    assert threads.commentable(patch) == {1, 2, 3, 10}


def test_a_line_moved_by_the_base_is_found_on_the_head_by_its_text() -> None:
    """CI checks out the merge commit; the comment goes on the head's line."""
    head = ["x = 1", "y = 2", "open()"]

    assert threads.nearest(head, "open()", 2) == 3
    assert threads.nearest(head, "gone()", 2) is None


def test_each_push_posts_the_new_resolves_the_fixed_and_keeps_the_rest() -> None:
    keep, new, off = _spot(1, "keep"), _spot(2, "new"), _spot(3, "off")
    again, unplaced = _spot(4, "again"), _spot(None, "unplaced")
    judged = _spot(5, "judged", blocking=False)
    shown = {STORE: {1, 2, 4, 5}}  # line 3 is off the diff
    had = [
        threads.Thread("T1", "keep", False),
        threads.Thread("T2", "gone", False),
        threads.Thread("T3", "again", True),
        threads.Thread("T4", "judged", True),
        threads.Thread("T5", "unplaced", False),
    ]

    plan = threads.plan([keep, new, new, off, again, judged, unplaced], shown, had)

    assert plan.post == [new]  # once, though found twice; off the diff, never
    # A place that stands but has no line keeps its thread open.
    assert [t.key for t in plan.resolve] == ["gone"]
    # A blocking place resolved while it stands comes back; an advisory one
    # a person resolved was judged, and stays resolved.
    assert [t.key for t in plan.reopen] == ["again"]


def test_every_reply_resolve_and_reopen_is_one_request_in_order() -> None:
    todo = threads.Plan(
        post=[],
        resolve=[threads.Thread("T2", "gone", False)],
        reopen=[threads.Thread("T3", "again", True)],
    )

    query, variables = threads.mutations(todo, "abc1234567")

    reply, resolve = query.index("r0: addPull"), query.index("s0: resolveReview")
    reopen, again = query.index("u0: unresolveReview"), query.index("q0: addPull")
    assert reply < resolve and reopen < again
    assert variables == {
        "fixed": "Fixed in `abc1234`.",
        "still": "Still here at `abc1234`.",
        "t0": "T2",
        "o0": "T3",
    }
    # GitHub refuses a variable the request declares but never uses.
    only_fixed, used = threads.mutations(todo._replace(reopen=[]), "abc1234567")
    assert "$still" not in only_fixed and "still" not in used


def test_a_thread_says_the_rule_and_carries_its_key() -> None:
    body = threads.body(_spot(2, "service.takes-session service:notes store abc"))
    bare = threads.body(_spot(2, "k")._replace(action="Takes its session"))

    assert body.startswith("**Takes its session** · `service.takes-session` · blocks")
    assert "A second session waits. Open none." in body
    assert threads.key_of(body) == "service.takes-session service:notes store abc"
    # A rule with no fix of its own does not say its title twice.
    assert bare.split("\n\n")[1] == "A second session waits."
