"""Every mechanism ``aegis add <plugin>`` is supposed to fire, checked once.

Three gaps shipped because a mechanism existed for in-tree services and
was never wired for the plugin path: a plugin's migrations never ran
(#1075), the cross-spec ``services_card.py`` was never restored so the
frontend died on import, and ``auto_requires`` is still never applied
(#1079). Each was found by hand, in a real project, one at a time.

``aegis_stack_conformance`` declares one of everything. This installs it
into a real generated project through the real CLI, with nothing mocked,
and asserts each mechanism left the consequence it is supposed to leave.
A fourth gap of the same shape fails here instead of in someone's stack.

Deliberately not covered: dashboard cards and modals, which need Flet
controls to import cleanly and are exercised end to end by the crawl4ai
reference plugin instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.cli.test_utils import run_aegis_command, run_aegis_init

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A bare database project with the conformance plugin added."""
    out = tmp_path_factory.mktemp("conformance")
    result = run_aegis_init("conf-app", components=["database"], output_dir=out)
    assert result.success, f"init failed: {result.stderr}"
    target = out / "conf-app"

    added = run_aegis_command(
        "add", "conformance", "--project-path", str(target), "--yes"
    )
    assert added.success, f"add conformance failed: {added.stderr}\n{added.stdout}"
    return target


def _read(project: Path, relative: str) -> str:
    path = project / relative
    assert path.is_file(), f"{relative} was never written"
    return path.read_text()


class TestFilesAndAnswers:
    def test_the_plugins_own_files_render(self, project: Path) -> None:
        assert (project / "app/services/conformance/api.py").is_file()
        assert (project / "app/cli/conformance.py").is_file()

    def test_the_plugin_is_recorded_in_answers(self, project: Path) -> None:
        answers = _read(project, ".copier-answers.yml")
        assert "name: conformance" in answers


class TestMigrations:
    """#1075: a plugin's declared migrations have to be written and run."""

    def test_the_migration_is_written(self, project: Path) -> None:
        versions = sorted((project / "alembic/versions").glob("*_conformance.py"))
        assert versions, "no migration was generated for the plugin"

    def test_the_migration_creates_the_declared_table(self, project: Path) -> None:
        """Applying it needs a synced project venv, which this test has
        no business building; that the revision is valid Python and
        creates the declared table is the property #1075 was about."""
        migration = next((project / "alembic/versions").glob("*_conformance.py"))
        body = migration.read_text()
        ast.parse(body)
        assert "conformance_row" in body
        assert "ix_conformance_row_label" in body

    def test_the_stamp_signature_is_registered(self, project: Path) -> None:
        """A migration with no signature opts out of the startup
        re-adoption that stamps instead of replaying DDL, so a plugin
        must be able to declare one."""
        registry = _read(
            project, "app/components/backend/startup/migration_signatures.py"
        )
        assert '"conformance"' in registry
        assert "conformance_row" in registry

    def test_the_schema_is_dropped_on_sqlite(self, project: Path) -> None:
        """The spec declares a Postgres schema; SQLite has none."""
        migration = next((project / "alembic/versions").glob("*_conformance.py"))
        body = migration.read_text()
        assert "CREATE SCHEMA" not in body
        assert "schema='conformance'" not in body


class TestCrossSpecFiles:
    """A plugin is a service on the dashboard, so the shared card that
    only exists when a project has services must come back with it."""

    def test_the_services_card_is_restored(self, project: Path) -> None:
        card = "app/components/frontend/dashboard/cards/services_card.py"
        assert (project / card).is_file(), (
            "cards/__init__.py imports ServicesCard once any plugin is "
            "present; the module has to exist or the frontend dies on import"
        )

    def test_the_cards_index_imports_what_exists(self, project: Path) -> None:
        index = _read(project, "app/components/frontend/dashboard/cards/__init__.py")
        for line in index.splitlines():
            if line.startswith("from .") and " import " in line:
                module = line.split()[1].lstrip(".").split(" ")[0]
                path = project / "app/components/frontend/dashboard/cards"
                assert (path / f"{module}.py").is_file(), (
                    f"cards/__init__.py imports {module}, which does not exist"
                )


class TestWiring:
    def test_the_router_is_mounted(self, project: Path) -> None:
        routing = _read(project, "app/components/backend/api/routing.py")
        assert "app.services.conformance.api" in routing
        assert "/api/v1/conformance" in routing

    def test_the_settings_mixin_is_composed(self, project: Path) -> None:
        config = _read(project, "app/core/config.py")
        assert "ConformanceSettingsMixin" in config

    def test_the_settings_import_sits_with_the_other_imports(
        self, project: Path
    ) -> None:
        """Injected next to the class it feeds, the import lands after a
        module constant and every generated project fails ``ruff check``
        with E402 the moment it installs a plugin."""
        module = ast.parse(_read(project, "app/core/config.py"))
        first_statement = next(
            (
                node.lineno
                for node in module.body
                if not isinstance(node, ast.Import | ast.ImportFrom)
                and not (
                    isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                )
            ),
            None,
        )
        assert first_statement is not None
        late = [
            node.lineno
            for node in module.body
            if isinstance(node, ast.Import | ast.ImportFrom)
            and node.lineno > first_statement
        ]
        assert not late, f"imports after line {first_statement}: {late}"

    def test_the_health_check_is_registered(self, project: Path) -> None:
        startup = _read(project, "app/components/backend/startup/component_health.py")
        assert "conformance_health" in startup
        assert 'register_service_health_check("Conformance"' in startup

    def test_the_cli_group_is_registered(self, project: Path) -> None:
        main = _read(project, "app/cli/main.py")
        assert "conformance" in main


class TestAutoRequires:
    """#1079: an option declaring ``auto_requires`` must install what it
    asks for, the way ``ai[sqlite]`` pulls in a database."""

    @pytest.mark.xfail(
        reason="#1079: compute_auto_requires is never called on the plugin path",
        strict=True,
    )
    def test_an_option_pulls_in_the_component_it_requires(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        out = tmp_path_factory.mktemp("conformance-objects")
        result = run_aegis_init("obj-app", components=["database"], output_dir=out)
        assert result.success, f"init failed: {result.stderr}"
        target = out / "obj-app"

        added = run_aegis_command(
            "add", "conformance[objects]", "--project-path", str(target), "--yes"
        )
        assert added.success, f"add failed: {added.stderr}"
        answers = (target / ".copier-answers.yml").read_text()
        assert "include_storage: true" in answers


class TestLateComponent:
    """A component added after the plugin has to reach the plugin's
    render-time gates.

    Jinja decides ``{% if include_worker %}`` when the tree is rendered.
    Installing the worker later changes the answer without re-rendering
    anything the plugin owns, so the plugin keeps the branch it was born
    with. The same is true of the in-tree documents service, whose
    ``extraction/dispatch.py`` stays on its no-worker branch after
    ``aegis add worker``.
    """

    @pytest.mark.xfail(
        reason="#1080: adding a component never re-renders installed plugin trees",
        strict=True,
    )
    def test_adding_a_component_rerenders_the_plugin(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        out = tmp_path_factory.mktemp("conformance-late")
        result = run_aegis_init("late-app", components=["database"], output_dir=out)
        assert result.success, f"init failed: {result.stderr}"
        target = out / "late-app"

        added = run_aegis_command(
            "add", "conformance", "--project-path", str(target), "--yes"
        )
        assert added.success, f"add conformance failed: {added.stderr}"
        dispatch = target / "app/services/conformance/dispatch.py"
        assert 'DISPATCH = "in-process"' in dispatch.read_text()

        worker = run_aegis_command(
            "add", "worker", "--project-path", str(target), "--yes"
        )
        assert worker.success, f"add worker failed: {worker.stderr}"
        assert 'DISPATCH = "worker"' in dispatch.read_text()
