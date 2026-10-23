"""The async pattern, read from the app's source: an async function runs
on the event loop with every other request, so blocking work in it (the
system model's build, a sleep, a subprocess) is handed to a thread."""

from pathlib import Path
import textwrap

from app.services.system import patterns
from app.services.system.async_patterns import ASYNC
from tests._files import write_tree


def _report(root: Path, source: str) -> patterns.Report:
    write_tree(root, {"maps/draw.py": textwrap.dedent(source)})
    return patterns.report(ASYNC, root)


def _broken(report: patterns.Report) -> list[str]:
    (rule,) = report.rules
    return [i.label for i in rule.violations]


def test_every_rule_says_why_and_holds_a_change() -> None:
    assert all(rule.why and rule.gate for rule in ASYNC.rules)


def test_a_blocking_call_on_the_loop_is_flagged(tmp_path: Path) -> None:
    """Known by where it is imported from, however it is spelled: the
    model's ``current``, ``time.sleep``, a sleep aliased."""
    report = _report(
        tmp_path,
        """
        import time
        from time import sleep as nap
        from app.core.ontology import current

        async def draw() -> list[str]:
            return [n.id for n in current().nodes]

        async def doze() -> None:
            time.sleep(1)

        async def rest() -> None:
            nap(1)
        """,
    )
    assert _broken(report) == [
        "maps/draw.py: draw",
        "maps/draw.py: doze",
        "maps/draw.py: rest",
    ]


def test_handed_to_a_thread_or_awaited_it_is_not(tmp_path: Path) -> None:
    """``to_thread(current)`` passes it, never calls it; an awaited one
    (either way of a conditional) is an async one; another module's
    ``current`` (a request's recording) is not the model's; a sync
    function blocks no loop of its own."""
    report = _report(
        tmp_path,
        """
        import asyncio
        from app.core import replays, series
        from app.core.ontology import current

        async def draw() -> None:
            model = await asyncio.to_thread(current)
            await asyncio.sleep(0)
            await (series.latest() if fresh else series.current())
            recording = replays.current()

        def nodes() -> list[str]:
            return [n.id for n in current().nodes]
        """,
    )
    assert _broken(report) == []
    assert [i.label for i in report.instances] == ["maps/draw.py: draw"]
