"""
Tests for ``ManualUpdater.add_service``.

The service-install path that the plugin resolver flow uses for
transitive ``required_services`` deps. Wraps ``add_component`` and
appends the migration steps (alembic bootstrap, migration generation,
``alembic upgrade``) that a real ``aegis add-service`` would run —
without those, the project ships an enabled service whose database
tables don't exist.

We mock at the migration-helper boundary so these tests don't need a
real alembic config or live database. The integration that exercises
the full path lives in ``tests/cli/test_add_plugin_resolver_integration.py``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from aegis.constants import AnswerKeys, StorageBackends
from aegis.core.manual_updater import ManualUpdater, UpdateResult

COPIER_ANSWERS = """\
# Changes here will be overwritten by Copier; NEVER EDIT MANUALLY
project_name: Demo
project_slug: demo
include_database: false
include_auth: false
_commit: None
_src_path: aegis/templates/copier-aegis-project
"""


@pytest.fixture
def fake_project(tmp_path: Path) -> Path:
    project = tmp_path / "demo"
    project.mkdir()
    (project / ".copier-answers.yml").write_text(COPIER_ANSWERS)
    return project


def _make_updater(project: Path) -> ManualUpdater:
    return ManualUpdater(project)


class TestAddServiceMigrationFlow:
    def test_service_with_migrations_runs_migration_pipeline(
        self, fake_project: Path
    ) -> None:
        """A service that ships a ``MIGRATION_SPECS`` entry should drive
        the full sequence: bootstrap alembic (if missing), generate the
        migration, then ``run_migrations``. ``add_service_command``
        does this inline today; ``add_service`` makes the same sequence
        reusable so the resolver flow doesn't skip it."""
        updater = _make_updater(fake_project)
        component_result = UpdateResult(component="auth", success=True)

        with (
            patch.object(
                updater, "add_component", return_value=component_result
            ) as add_component_mock,
            patch.object(updater, "run_post_generation_tasks") as run_post_gen_mock,
            patch(
                "aegis.core.migration_generator.MIGRATION_SPECS",
                {"auth": object()},
            ),
            patch("aegis.core.migration_generator.bootstrap_alembic") as bootstrap_mock,
            patch(
                "aegis.core.migration_generator.service_has_migration",
                return_value=False,
            ),
            patch("aegis.core.migration_generator.generate_migration") as generate_mock,
            patch("aegis.core.post_gen_tasks.run_migrations") as run_mig_mock,
        ):
            result = updater.add_service("auth")

        assert result.success
        # add_component is the file-install step — called with
        # run_post_gen=False so post-gen happens once at the end.
        add_component_mock.assert_called_once_with("auth", None, run_post_gen=False)
        # Service has no alembic dir on a fresh fixture — bootstrap fires.
        bootstrap_mock.assert_called_once()
        # Migration not yet present → generated, with the project's answers
        # as context so engine-specific rendering (schemas) resolves.
        generate_mock.assert_called_once_with(fake_project, "auth", updater.answers)
        run_mig_mock.assert_called_once_with(fake_project, include_migrations=True)
        # Default run_post_gen=True drives the trailing sync/format pass.
        run_post_gen_mock.assert_called_once()

    def test_migration_generation_receives_project_engine(
        self, fake_project: Path
    ) -> None:
        """The generator drops a declared Postgres schema on engines that
        have none, which it can only do if it knows the project's engine.
        So the project's answers ride along as generation context.

        Without this, a plugin declaring ``MigrationSpec(schema=...)`` emits
        ``CREATE SCHEMA`` into a SQLite project's migration.
        """
        (fake_project / ".copier-answers.yml").write_text(
            COPIER_ANSWERS + f"{AnswerKeys.DATABASE_ENGINE}: {StorageBackends.SQLITE}\n"
        )
        updater = _make_updater(fake_project)
        component_result = UpdateResult(component="crawler", success=True)

        with (
            patch.object(updater, "add_component", return_value=component_result),
            patch.object(updater, "run_post_generation_tasks"),
            patch(
                "aegis.core.migration_generator.MIGRATION_SPECS",
                {"crawler": object()},
            ),
            patch("aegis.core.migration_generator.bootstrap_alembic"),
            patch(
                "aegis.core.migration_generator.service_has_migration",
                return_value=False,
            ),
            patch("aegis.core.migration_generator.generate_migration") as generate_mock,
            patch("aegis.core.post_gen_tasks.run_migrations"),
        ):
            updater.add_service("crawler")

        generate_mock.assert_called_once()
        context = generate_mock.call_args.args[2]
        assert context[AnswerKeys.DATABASE_ENGINE] == StorageBackends.SQLITE

    def test_service_without_migrations_skips_migration_pipeline(
        self, fake_project: Path
    ) -> None:
        """A service NOT in ``MIGRATION_SPECS`` (e.g., a pure-code
        service) should still install via ``add_component`` but skip
        the migration tail entirely. Asserting this so we don't
        accidentally bootstrap alembic for services that have no
        database surface."""
        updater = _make_updater(fake_project)
        component_result = UpdateResult(component="comms", success=True)

        with (
            patch.object(updater, "add_component", return_value=component_result),
            patch.object(updater, "run_post_generation_tasks"),
            patch("aegis.core.migration_generator.MIGRATION_SPECS", {}),
            patch("aegis.core.migration_generator.bootstrap_alembic") as bootstrap_mock,
            patch("aegis.core.migration_generator.generate_migration") as generate_mock,
            patch("aegis.core.post_gen_tasks.run_migrations") as run_mig_mock,
        ):
            result = updater.add_service("comms")

        assert result.success
        bootstrap_mock.assert_not_called()
        generate_mock.assert_not_called()
        run_mig_mock.assert_not_called()

    def test_run_post_gen_false_skips_post_generation(self, fake_project: Path) -> None:
        """Caller batching multiple installs (the resolver flow) passes
        ``run_post_gen=False`` so each ``add_service`` skips its own
        ``uv sync``/``make fix`` pass — they run once at the very end
        of the whole operation."""
        updater = _make_updater(fake_project)
        component_result = UpdateResult(component="comms", success=True)

        with (
            patch.object(updater, "add_component", return_value=component_result),
            patch.object(updater, "run_post_generation_tasks") as run_post_gen_mock,
            patch("aegis.core.migration_generator.MIGRATION_SPECS", {}),
        ):
            updater.add_service("comms", run_post_gen=False)

        run_post_gen_mock.assert_not_called()

    def test_failed_add_component_short_circuits(self, fake_project: Path) -> None:
        """If the file-install half fails, the migration tail should NOT
        run — there's nothing to migrate against. The propagated result
        carries the failure."""
        updater = _make_updater(fake_project)
        component_result = UpdateResult(
            component="auth", success=False, error_message="boom"
        )

        with (
            patch.object(updater, "add_component", return_value=component_result),
            patch.object(updater, "run_post_generation_tasks") as run_post_gen_mock,
            patch("aegis.core.migration_generator.bootstrap_alembic") as bootstrap_mock,
        ):
            result = updater.add_service("auth")

        assert not result.success
        assert result.error_message == "boom"
        bootstrap_mock.assert_not_called()
        run_post_gen_mock.assert_not_called()


class TestAddComponentRunPostGenFlag:
    def test_run_post_gen_false_skips_post_generation(self, fake_project: Path) -> None:
        """``add_component(..., run_post_gen=False)`` must not invoke
        the trailing sync. Anchors the F4 contract that the resolver
        flow relies on — without this, batching deps still produces
        N+1 sync passes."""
        updater = _make_updater(fake_project)

        with (
            patch.object(updater, "_render_template_file", return_value="content"),
            patch.object(
                updater, "_regenerate_shared_files", return_value=([], [], [])
            ),
            patch.object(updater, "_save_answers"),
            patch.object(updater, "run_post_generation_tasks") as run_post_gen_mock,
            # Mock the file write since the fixture project has no
            # template tree.
            patch("aegis.core.manual_updater.get_component_files", return_value=[]),
        ):
            updater.add_component("worker", None, run_post_gen=False)

        run_post_gen_mock.assert_not_called()

    def test_run_post_gen_default_true_calls_post_generation(
        self, fake_project: Path
    ) -> None:
        """Without the keyword (existing call sites), behaviour is
        unchanged — post-gen still fires."""
        updater = _make_updater(fake_project)

        with (
            patch.object(updater, "_render_template_file", return_value="content"),
            patch.object(
                updater, "_regenerate_shared_files", return_value=([], [], [])
            ),
            patch.object(updater, "_save_answers"),
            patch.object(updater, "run_post_generation_tasks") as run_post_gen_mock,
            patch("aegis.core.manual_updater.get_component_files", return_value=[]),
        ):
            updater.add_component("worker", None)

        run_post_gen_mock.assert_called_once()
