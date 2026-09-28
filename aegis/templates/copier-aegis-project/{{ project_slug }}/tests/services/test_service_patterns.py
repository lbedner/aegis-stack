"""The service pattern, read from the service source files.

A service function that touches the database takes its session from the
caller and never opens one; the caller (a route's dependency, a job, a
task) owns the unit of work. Entry points with no caller (jobs, health
checks) open the one session and pass it down.
"""

from pathlib import Path
import textwrap

from app.services.system import patterns
from app.services.system.service_patterns import SERVICE


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source))


def _findings(root: Path) -> dict[str, list[str]]:
    report = patterns.report(SERVICE, root)
    return {rule.key: [i.label for i in rule.violations] for rule in report.rules}


def test_every_rule_says_why() -> None:
    assert all(rule.why for rule in SERVICE.rules)


def test_a_function_opening_its_own_session_is_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "notes/store.py",
        """
        async def save(text: str) -> None:
            async with get_async_session() as session:
                session.add(text)
        """,
    )
    assert _findings(tmp_path)["takes-session"] == ["notes/store.py: save"]


def test_entry_points_may_open_the_session(tmp_path: Path) -> None:
    for module in ("notes/jobs.py", "notes/health.py", "notes/health_store.py"):
        _write(
            tmp_path,
            module,
            """
            async def run() -> None:
                async with get_async_session() as session:
                    await prune(session)
            """,
        )
    assert _findings(tmp_path)["takes-session"] == []


def test_an_optional_session_is_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "notes/store.py",
        """
        class Store:
            async def count(self, session: AsyncSession | None = None) -> int:
                return await session.scalar(select(1))
        """,
    )
    assert _findings(tmp_path)["required-session"] == ["notes/store.py: Store.count"]


def test_a_required_session_follows_and_becomes_the_example(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "notes/store.py",
        """
        async def count(session: AsyncSession, owner_id: int) -> int:
            \"\"\"How many notes the owner has.\"\"\"
            return await session.scalar(select(1))
        """,
    )
    report = patterns.report(SERVICE, tmp_path)
    assert [i.findings for i in report.instances] == [[]]
    assert report.canonical is not None
    code, path = patterns.source(SERVICE.function(report.canonical.target))
    assert "async def count" in code and path.endswith("store.py")


def test_the_shipped_services_are_found() -> None:
    report = patterns.report(SERVICE)
    assert report.instances
    assert all(i.label.split(": ")[0].endswith(".py") for i in report.instances)
