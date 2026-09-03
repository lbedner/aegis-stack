"""``add-service documents`` must land what ``init --services documents`` does.

Documents is the most wired service in the tree: a migration, a worker task
registered on three backends, its own API routes plus the generic jobs
surface, storage, a card, a modal, and an entry in the architecture diagram.
Every one of those is a chance for the add path to write a file the init
path renames, skip one it never learned about, or leave a variant behind.

That is not hypothetical. #1033 was this shape for ``aegis add worker`` -
the bracket was parsed and the entrypoint was not regenerated, so the
container launched a runner the project never installed - and the health
modules in #1046 were rewritten by the add path after cleanup had removed
them, because no manifest claimed them.

The comparison is the point: generate the service, add the service, and
diff what the service owns. A file present in one and not the other, or
holding different bytes, is the bug these tests exist to catch.
"""

from __future__ import annotations

import ast
from difflib import unified_diff
from pathlib import Path

import pytest

from aegis.core.services import SERVICES
from tests.cli.test_utils import run_aegis_command, run_aegis_init

# Rendered per project rather than per service: the answers file records the
# whole stack, and the diagram and card registries list every service the
# project has, so they differ between "generated with" and "added to" for
# reasons that are not documents' fault.
_PROJECT_SHAPED = (
    ".copier-answers.yml",
    "app/components/frontend/dashboard/cards/__init__.py",
    "app/components/frontend/dashboard/modals/__init__.py",
)


def _clear_cli_selections() -> None:
    """Reset the option globals the in-process CLI keeps between invocations.

    ``run_aegis_init`` does this before every init for a known reason: the
    CliRunner runs in this process, so a bracket option another test chose
    (``auth[org]``, ``ai[...]``) is still set when the next command runs. The
    add path needs the same clean slate, or what it renders depends on which
    tests ran before it - which is how this test failed in CI while passing
    when its file was run alone.
    """
    from aegis.cli.interactive import (
        clear_all_ai_selections,
        clear_auth_level_selection,
        clear_database_engine_selection,
        clear_postgres_provider_selection,
    )

    clear_auth_level_selection()
    clear_database_engine_selection()
    clear_postgres_provider_selection()
    clear_all_ai_selections()


def _comparable(name: str, text: str) -> list[str]:
    """The file as code, not as text.

    Both paths format what they write, but whether the pass reaches every
    file depends on the environment: CI has shown the same file with
    imports in a different order on one side and a call wrapped across
    three lines on the other, with identical code underneath. Comparing
    parsed statements says what this test means - the add path produces the
    same code - and still fails on a changed argument, a dropped import or
    an extra branch.
    """
    if not name.endswith(".py"):
        return text.splitlines()

    tree = ast.parse(text)
    is_import = (ast.Import, ast.ImportFrom)
    imports = sorted(ast.dump(n) for n in tree.body if isinstance(n, is_import))
    body = [ast.dump(n) for n in tree.body if not isinstance(n, is_import)]
    return imports + body


def _owned_files(project: Path) -> dict[str, str]:
    """Every documents-owned file that exists, mapped to its contents."""
    owned: dict[str, str] = {}
    for entry in SERVICES["documents"].files.primary:
        target = project / entry
        if target.is_dir():
            for path in sorted(target.rglob("*.py")):
                owned[str(path.relative_to(project))] = path.read_text()
        elif target.is_file():
            owned[entry] = target.read_text()
    return {k: v for k, v in owned.items() if k not in _PROJECT_SHAPED}


@pytest.fixture(scope="module")
def added(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A base project with documents added afterwards."""
    out = tmp_path_factory.mktemp("added")
    result = run_aegis_init("docs-app", components=["database"], output_dir=out)
    assert result.success, f"init failed: {result.stderr}"
    project = out / "docs-app"

    _clear_cli_selections()
    added = run_aegis_command(
        "add-service", "documents", "--project-path", str(project), "--yes"
    )
    assert added.success, f"add-service documents failed: {added.stderr}"
    return project


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The same project, generated with documents from the start."""
    out = tmp_path_factory.mktemp("generated")
    result = run_aegis_init(
        "docs-app", components=["database"], services=["documents"], output_dir=out
    )
    assert result.success, f"init failed: {result.stderr}"
    return out / "docs-app"


def test_the_add_path_writes_every_file_the_init_path_does(
    added: Path, generated: Path
) -> None:
    missing = sorted(set(_owned_files(generated)) - set(_owned_files(added)))
    assert not missing, f"add-service documents never wrote: {missing}"


def test_the_add_path_writes_nothing_the_init_path_does_not(
    added: Path, generated: Path
) -> None:
    """The direction that actually bit us.

    #1046's health modules were the add path writing variant files after
    cleanup had removed them - files a project generated with the service
    never has. A comparison that only looks for what is missing cannot see
    that, and it is the more likely failure: the add path errs by writing
    too much, because it renders before it knows what to keep.
    """
    extra = sorted(set(_owned_files(added)) - set(_owned_files(generated)))
    assert not extra, f"add-service documents left files init never writes: {extra}"


def test_no_file_differs_between_the_two_paths(added: Path, generated: Path) -> None:
    from_add, from_init = _owned_files(added), _owned_files(generated)
    differing = sorted(
        name
        for name in set(from_add) & set(from_init)
        if _comparable(name, from_add[name]) != _comparable(name, from_init[name])
    )
    detail = ""
    if differing:
        first = differing[0]
        detail = "\n".join(
            list(
                unified_diff(
                    _comparable(first, from_init[first]),
                    _comparable(first, from_add[first]),
                    fromfile=f"init/{first}",
                    tofile=f"add/{first}",
                    lineterm="",
                    n=1,
                )
            )[:20]
        )
    assert not differing, (
        f"these render differently depending on how documents arrived: "
        f"{differing}\n\n{detail}"
    )


def test_the_migration_lands(added: Path) -> None:
    """Without it the tables never exist, and nothing says so until runtime."""
    versions = (added / "alembic/versions").glob("*.py")
    assert any("document" in p.read_text() for p in versions), (
        "no migration creating the document tables"
    )


def test_the_service_is_wired_into_the_dashboard(added: Path) -> None:
    cards = (added / "app/components/frontend/dashboard/cards/__init__.py").read_text()
    modals = (
        added / "app/components/frontend/dashboard/modals/__init__.py"
    ).read_text()

    assert "DocumentsCard" in cards
    assert "DocumentsDetailDialog" in modals


def test_the_api_is_mounted(added: Path) -> None:
    """Both surfaces: the service's own routes, and the jobs feed it uses."""
    routing = (added / "app/components/backend/api/routing.py").read_text()

    assert "documents" in routing
    assert "jobs" in routing


def test_a_worker_project_gets_the_task_registered(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """The extraction task must reach the queue of the backend in use.

    Documents ships one task file per backend and the init path renames the
    right one into place. An add path that skips the rename leaves a project
    whose dispatch enqueues a task its worker never registered - the job sits
    "Queued..." forever, which is #1033's failure with a different cause.
    """
    out = tmp_path_factory.mktemp("worker-then-documents")
    result = run_aegis_init(
        "wk-app", components=["worker[taskiq]", "database"], output_dir=out
    )
    assert result.success, f"init failed: {result.stderr}"
    project = out / "wk-app"

    _clear_cli_selections()
    added = run_aegis_command(
        "add-service", "documents", "--project-path", str(project), "--yes"
    )
    assert added.success, f"add-service documents failed: {added.stderr}"

    system_queue = (project / "app/components/worker/queues/system.py").read_text()
    assert "extract_document_task" in system_queue, (
        "the extraction task never reached the system queue"
    )
    assert "broker.task" in system_queue, "the queue is not this project's backend"

    dispatch = (
        project / "app/services/documents/domains/extraction/dispatch.py"
    ).read_text()
    assert "kiq(" in dispatch, "dispatch does not enqueue through TaskIQ"

    assert (project / "app/services/system/job_relay.py").exists(), (
        "the jobs relay a worker's progress is read through is missing"
    )
