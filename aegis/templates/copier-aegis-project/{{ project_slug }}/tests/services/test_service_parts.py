"""The parts pattern: each service checked against the service standard
(``docs/services/index.md``), read from a project tree: which parts it
has, which rules it breaks, with the ``path:line`` that shows it."""

from pathlib import Path
import re
import textwrap

import pytest

from app.core import source_index
from app.services.system import pattern_findings, patterns, service_parts
from app.services.system.service_parts import PARTS
from tests._files import write_tree

ROUTER = "app/components/backend/api/notes/router.py"


def _write(root: Path, relative: str, source: str = "") -> None:
    write_tree(root, {relative: textwrap.dedent(source)})


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A service with every part, following every rule."""
    for module in ("__init__", "service", "models", "health"):
        _write(tmp_path, f"app/services/notes/{module}.py")
    _write(
        tmp_path,
        "app/services/notes/queries.py",
        """
        async def count(session):
            return (await session.exec(select(1))).one()
        """,
    )
    _write(
        tmp_path,
        "app/services/notes/jobs.py",
        """
        async def prune_job() -> None:
            pass

        JOBS = [prune_job]
        """,
    )
    _write(tmp_path, ROUTER, "async def read() -> None:\n    pass\n")
    _write(tmp_path, "tests/test_notes.py", "from app.services.notes import service\n")
    return tmp_path


def _report(root: Path) -> patterns.Report:
    return patterns.report(PARTS, root)


def _broken(root: Path) -> dict[str, list[str]]:
    return {r.key: [i.label for i in r.violations] for r in _report(root).rules}


def _evidence(root: Path, check: str) -> list[str]:
    found = pattern_findings.findings(_report(root))
    return [e for f in found if f.check == f"parts.{check}" for e in f.evidence]


def test_every_rule_says_why() -> None:
    assert all(rule.why for rule in PARTS.rules)


def test_a_service_with_every_part_breaks_nothing(project: Path) -> None:
    report = _report(project)
    assert [i.label for i in report.instances] == ["service:notes"]
    assert not any(_broken(project).values())
    assert all(s.followed == s.applicable == 1 for s in report.steps)
    assert report.canonical is not None


def test_a_missing_health_check_is_flagged(project: Path) -> None:
    (project / "app/services/notes/health.py").unlink()
    assert _broken(project)["has-health"] == ["service:notes"]
    assert _evidence(project, "has-health") == ["app/services/notes/__init__.py:1"]


def test_a_job_nothing_runs_is_flagged(project: Path) -> None:
    _write(
        project,
        "app/services/notes/jobs.py",
        """
        async def prune_job() -> None:
            pass


        async def forgotten_job() -> None:
            pass

        JOBS = [prune_job]
        """,
    )
    assert _broken(project)["jobs-wired"] == ["service:notes"]
    assert _evidence(project, "jobs-wired") == ["app/services/notes/jobs.py:6"]


def test_a_job_called_from_elsewhere_is_wired(project: Path) -> None:
    _write(project, "app/services/notes/jobs.py", "async def prune_job():\n    pass\n")
    _write(
        project,
        "app/services/notes/scheduled_jobs.py",
        "from app.services.notes.jobs import prune_job\n",
    )
    assert _broken(project)["jobs-wired"] == []


def test_a_router_querying_the_database_is_flagged(project: Path) -> None:
    _write(
        project,
        ROUTER,
        """
        from sqlmodel import select

        async def read(session) -> None:
            return (await session.exec(select(1))).all()
        """,
    )
    assert _broken(project)["router-no-db"] == ["service:notes"]
    assert _evidence(project, "router-no-db") == [f"{ROUTER}:2", f"{ROUTER}:5"]


def test_a_read_outside_queries_is_flagged_but_a_seed_is_not(project: Path) -> None:
    read = "async def all(session):\n    return await session.exec(q)\n"
    _write(project, "app/services/notes/store.py", read)
    _write(project, "app/services/notes/seed.py", read)
    assert _broken(project)["reads-in-queries"] == ["service:notes"]
    assert _evidence(project, "reads-in-queries") == ["app/services/notes/store.py:2"]


def test_logic_outside_a_standard_file_belongs_in_a_domain(project: Path) -> None:
    """The standard names a service's top-level files (``PIECES``); any
    other module or package is a subsystem, which lives under domains/."""
    for module in (
        "slugs.py",
        "providers/__init__.py",
        "providers/stripe.py",
        "domains/__init__.py",
        "domains/tags/__init__.py",
        "schemas.py",
        "tools.py",
        "change_types.py",
        "adapters/__init__.py",
        "adapters/plaid.py",
        "seed.py",
    ):
        _write(project, f"app/services/notes/{module}")
    assert _broken(project)["domains"] == ["service:notes"]
    assert _evidence(project, "domains") == [
        "app/services/notes/providers/__init__.py:1",
        "app/services/notes/slugs.py:1",
    ]


def _lines(count: int) -> str:
    return "x = 1\n" * count


def test_a_file_past_its_size_budget_is_flagged(project: Path) -> None:
    """A file is what an agent loads whole: logic past 500 lines is flagged,
    a list (models, schemas) only past 900."""
    _write(project, "app/services/notes/service.py", _lines(501))
    for listing in ("models", "schemas"):  # two, so neither is most of it
        _write(project, f"app/services/notes/{listing}.py", _lines(800))
    assert _broken(project)["size"] == ["service:notes"]
    assert _evidence(project, "size") == ["app/services/notes/service.py:1"]
    index = source_index.at(project)
    note = service_parts.size_note("app/services/notes/service.py", index)
    assert note == "501 lines; the limit is 500"


def test_one_file_holding_most_of_its_package_is_flagged(project: Path) -> None:
    """Under every cap, a package of stubs around one long file is still one
    file wearing a folder: its largest, past 40% of it and 400 lines."""
    folder = "app/services/notes/domains/tags"
    _write(project, f"{folder}/__init__.py", _lines(100))
    _write(project, f"{folder}/rules.py", _lines(450))
    _write(project, f"{folder}/names.py", _lines(300))
    assert _evidence(project, "size") == [f"{folder}/rules.py:1"]
    _write(project, f"{folder}/names.py", _lines(460))
    assert _evidence(project, "size") == [f"{folder}/names.py:1"]
    note = service_parts.size_note(f"{folder}/names.py", source_index.at(project))
    assert note == "460 of the 1,010 lines in its folder: too much for one file"


def test_every_module_looked_up_by_name_is_a_standard_part() -> None:
    """A file the app finds by its name in every service (``tools``,
    ``models``, ``sources``...) is part of the standard, never a loose
    module: one list, so a new convention cannot miss it."""
    from app.core.source_index import ROOT
    from app.services.system.service_parts import PIECES

    looked_up = {
        name
        for path in (ROOT / "app").rglob("*.py")
        for name in re.findall(r'modules_named\(services, "(\w+)"\)', path.read_text())
    }
    assert looked_up and looked_up <= set(PIECES), looked_up - set(PIECES)
    assert "sources" in PIECES  # research plugins' registrations


def test_parts_a_service_lacks_are_counted_not_failed(project: Path) -> None:
    """Optional parts are inventory: a service with no jobs or router has
    fewer parts, and breaks no rule for it."""
    (project / "app/services/notes/jobs.py").unlink()
    (project / ROUTER).unlink()
    report = _report(project)
    steps = {s.label: s.followed for s in report.steps}
    assert steps["Jobs"] == steps["Router"] == 0
    assert not any(_broken(project).values())
    # Nor does it miss them: only an expected part (``EXPECTED``) is missed.
    assert report.instances[0].missed == []
    (project / "tests/test_notes.py").unlink()
    assert _report(project).instances[0].missed == ["Tests"]


def test_a_service_that_reads_nothing_lacks_no_queries(project: Path) -> None:
    """Queries holds a service's reads: one with none needs no module for
    them, so it is not missing one; a read with nowhere to live is."""
    (project / "app/services/notes/queries.py").unlink()
    steps = {s.label: s.followed for s in _report(project).steps}
    assert steps["Queries"] == 1
    _write(
        project,
        "app/services/notes/service.py",
        "async def count(session):\n    return await session.exec(select(1))\n",
    )
    steps = {s.label: s.followed for s in _report(project).steps}
    assert steps["Queries"] == 0


def test_findings_are_typed_and_fingerprinted(project: Path) -> None:
    (project / "app/services/notes/health.py").unlink()
    first = pattern_findings.findings(_report(project))
    assert first == pattern_findings.findings(_report(project))
    (finding,) = first
    assert finding.check == "parts.has-health"
    assert finding.subject == "service:notes"
    assert finding.severity == "error"
    assert finding.why and finding.action


def test_a_fingerprint_changes_with_its_evidence(project: Path) -> None:
    unwired = "async def prune_job():\n    pass\n"
    _write(project, "app/services/notes/jobs.py", unwired)
    (before,) = pattern_findings.findings(_report(project))
    _write(project, "app/services/notes/jobs.py", "\n" + unwired)
    (after,) = pattern_findings.findings(_report(project))
    assert before.evidence != after.evidence
    assert before.fingerprint != after.fingerprint
