"""
Integration test for ``aegis add`` + plugin dependency resolution (#776).

The resolver itself is unit-tested in
``tests/core/test_plugin_resolver.py``. This file fills the gap: it
exercises the actual ``_install_plugin`` path with a plugin that
declares ``required_services=["auth"]`` and asserts the resolver kicks
in — that the in-tree dependency is installed first, the target plugin
second, and the plan is shown to the user.

Plumbing is mocked at the ``ManualUpdater`` boundary so the test stays
fast and doesn't generate a real project; what we're checking is the
*orchestration*, not template rendering.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from aegis.commands.add import add_command
from aegis.core.plugins.spec import PluginKind, PluginSpec

# Local Typer app so we can invoke ``add_command`` without the
# project's full CLI tree (which would pull in plugin discovery from
# the live entry-point set and complicate the patch surface).
app = typer.Typer()
app.command(name="add")(add_command)
runner = CliRunner()


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
    """Project shaped just enough for ``add_command`` to bind:

    * ``.copier-answers.yml`` so ``validate_copier_project`` passes.
    * ``git init`` so ``validate_git_repository`` passes.
    * ``include_auth: false`` so the resolver actually queues auth
      as a missing dep.
    """
    project = tmp_path / "demo"
    project.mkdir()
    (project / ".copier-answers.yml").write_text(COPIER_ANSWERS)
    subprocess.run(["git", "init", "--quiet"], cwd=project, check=True)
    return project


def _fake_plugin_with_dep() -> PluginSpec:
    """Synthetic plugin that requires ``auth`` (an in-tree service)."""
    return PluginSpec(
        name="needs_auth",
        kind=PluginKind.SERVICE,
        description="Plugin that depends on auth",
        version="0.0.1",
        verified=False,
        required_services=["auth"],
    )


class TestResolverIntegration:
    def test_required_service_installed_before_target(self, fake_project: Path) -> None:
        """When ``aegis add needs_auth`` runs and auth isn't installed,
        the resolver should drive ``ManualUpdater.add_component('database')``
        for the component dep, ``ManualUpdater.add_service('auth')`` for
        the service dep (so its migrations get bootstrapped + run), and
        ``ManualUpdater.add_plugin(needs_auth)`` for the target plugin.

        Service deps must NOT go through ``add_component`` directly — that
        would set the include flag but skip alembic bootstrap and migration
        generation, leaving the project with an enabled service whose
        tables don't exist."""
        spec = _fake_plugin_with_dep()
        call_order: list[str] = []

        def _add_component_side_effect(name: str, _data, **_kw) -> MagicMock:
            call_order.append(f"add_component:{name}")
            return MagicMock(success=True, error_message=None)

        def _add_service_side_effect(name: str, _data, **_kw) -> MagicMock:
            call_order.append(f"add_service:{name}")
            return MagicMock(success=True, error_message=None)

        def _add_plugin_side_effect(
            spec, plugin_module_name, plugin_options=None, **_kw
        ) -> MagicMock:
            call_order.append(f"add_plugin:{spec.name}")
            return MagicMock(success=True, error_message=None)

        mock_updater = MagicMock()
        mock_updater.add_component.side_effect = _add_component_side_effect
        mock_updater.add_service.side_effect = _add_service_side_effect
        mock_updater.add_plugin.side_effect = _add_plugin_side_effect

        # ``_resolve_plugin`` returns the synthetic spec; no entry-point
        # discovery happens. Module name is a placeholder — the
        # mocked updater never reads it.
        with (
            patch(
                "aegis.commands.add._resolve_plugin",
                return_value=(spec, "fake_module"),
            ),
            patch(
                "aegis.commands.add.ManualUpdater",
                return_value=mock_updater,
            ),
            patch(
                "aegis.commands.add.validate_version_compatibility",
                return_value=None,
            ),
        ):
            result = runner.invoke(
                app,
                ["needs_auth", "--project-path", str(fake_project), "--yes"],
            )

        assert result.exit_code == 0, result.output
        # The plan summary should mention the required service.
        assert "auth" in result.output
        # Topological order: auth's own ``required_components=["database"]``
        # gets walked transitively, so database lands first as a component,
        # then auth as a service (with migration bootstrap), then the
        # target plugin.
        assert call_order == [
            "add_component:database",
            "add_service:auth",
            "add_plugin:needs_auth",
        ]

    def test_variant_dep_upgrades_installed_service(self, fake_project: Path) -> None:
        """Project has basic auth; the plugin requires ``auth[org]``. The
        resolver must not treat auth as present: ``add_service`` is called
        with the org level so the upgrade path runs."""
        answers = fake_project / ".copier-answers.yml"
        answers.write_text(
            answers.read_text().replace(
                "include_auth: false", "include_auth: true\nauth_level: basic"
            )
        )
        spec = PluginSpec(
            name="needs_org",
            kind=PluginKind.SERVICE,
            description="Plugin that depends on org-level auth",
            version="0.0.1",
            verified=False,
            required_services=["auth[org]"],
        )
        calls: list[tuple[str, dict | None]] = []

        def _add_service_side_effect(name: str, data, **_kw) -> MagicMock:
            calls.append((name, data))
            return MagicMock(success=True, error_message=None)

        mock_updater = MagicMock()
        mock_updater.add_service.side_effect = _add_service_side_effect
        mock_updater.add_component.return_value = MagicMock(success=True)
        mock_updater.add_plugin.return_value = MagicMock(success=True)

        with (
            patch(
                "aegis.commands.add._resolve_plugin",
                return_value=(spec, "fake_module"),
            ),
            patch("aegis.commands.add.ManualUpdater", return_value=mock_updater),
            patch(
                "aegis.commands.add.validate_version_compatibility",
                return_value=None,
            ),
        ):
            result = runner.invoke(
                app,
                ["needs_org", "--project-path", str(fake_project), "--yes"],
            )

        assert result.exit_code == 0, result.output
        assert calls == [("auth", {"auth_level": "org"})]

    def test_conflicting_variant_dep_is_refused(self, fake_project: Path) -> None:
        """``ai[langchain]`` required on a pydantic-ai project is a conflict:
        the command exits non-zero before installing anything."""
        answers = fake_project / ".copier-answers.yml"
        answers.write_text(
            answers.read_text() + "include_ai: true\nai_framework: pydantic-ai\n"
        )
        spec = PluginSpec(
            name="needs_langchain",
            kind=PluginKind.SERVICE,
            description="Plugin that depends on the LangChain framework",
            version="0.0.1",
            verified=False,
            required_services=["ai[langchain]"],
        )
        mock_updater = MagicMock()
        with (
            patch(
                "aegis.commands.add._resolve_plugin",
                return_value=(spec, "fake_module"),
            ),
            patch("aegis.commands.add.ManualUpdater", return_value=mock_updater),
            patch(
                "aegis.commands.add.validate_version_compatibility",
                return_value=None,
            ),
        ):
            result = runner.invoke(
                app,
                ["needs_langchain", "--project-path", str(fake_project), "--yes"],
            )

        assert result.exit_code == 1
        mock_updater.add_service.assert_not_called()
        mock_updater.add_plugin.assert_not_called()

    def test_dep_install_runs_post_gen_exactly_once(self, fake_project: Path) -> None:
        """Adding a plugin with N transitive deps must trigger exactly
        ONE ``run_post_generation_tasks`` invocation across the whole
        operation, not N+1.

        Each ``add_component`` / ``add_service`` / ``add_plugin`` call
        used to end with its own ``uv sync`` + ``make fix`` pass, so a
        plugin with a chain of deps would re-sync after every dep.
        Now they all pass ``run_post_gen=False`` and the outermost
        ``_install_plugin`` runs post-gen once at the end."""
        spec = _fake_plugin_with_dep()  # needs_auth → auth → database

        mock_updater = MagicMock()
        mock_updater.add_component.return_value = MagicMock(
            success=True, error_message=None
        )
        mock_updater.add_service.return_value = MagicMock(
            success=True, error_message=None
        )
        mock_updater.add_plugin.return_value = MagicMock(
            success=True, error_message=None
        )

        with (
            patch(
                "aegis.commands.add._resolve_plugin",
                return_value=(spec, "fake_module"),
            ),
            patch(
                "aegis.commands.add.ManualUpdater",
                return_value=mock_updater,
            ),
            patch(
                "aegis.commands.add.validate_version_compatibility",
                return_value=None,
            ),
        ):
            result = runner.invoke(
                app,
                ["needs_auth", "--project-path", str(fake_project), "--yes"],
            )

        assert result.exit_code == 0, result.output

        # Every dep / target install should pass run_post_gen=False so
        # they don't fire sync individually.
        for call in mock_updater.add_component.call_args_list:
            assert call.kwargs.get("run_post_gen") is False, (
                f"add_component called without run_post_gen=False: {call}"
            )
        for call in mock_updater.add_service.call_args_list:
            assert call.kwargs.get("run_post_gen") is False, (
                f"add_service called without run_post_gen=False: {call}"
            )
        for call in mock_updater.add_plugin.call_args_list:
            assert call.kwargs.get("run_post_gen") is False, (
                f"add_plugin called without run_post_gen=False: {call}"
            )

        # And the outer flow runs post-gen exactly once.
        assert mock_updater.run_post_generation_tasks.call_count == 1

    def test_declining_confirmation_installs_nothing(self, fake_project: Path) -> None:
        """A single confirmation gates the entire plan. If the user
        declines, neither the dependencies nor the target plugin should
        be touched — the project must be left in its original state.

        Earlier versions split this into two confirmations and installed
        deps between them, leaving a partial state when the user said
        yes to deps but no to the target. The consolidated single-prompt
        flow makes that bug structurally impossible.
        """
        spec = _fake_plugin_with_dep()
        mock_updater = MagicMock()
        mock_updater.add_component.return_value = MagicMock(
            success=True, error_message=None
        )
        mock_updater.add_plugin.return_value = MagicMock(
            success=True, error_message=None
        )

        with (
            patch(
                "aegis.commands.add._resolve_plugin",
                return_value=(spec, "fake_module"),
            ),
            patch(
                "aegis.commands.add.ManualUpdater",
                return_value=mock_updater,
            ),
            patch(
                "aegis.commands.add.validate_version_compatibility",
                return_value=None,
            ),
        ):
            # No --yes flag → typer.confirm prompt fires; "n\n" answers no.
            result = runner.invoke(
                app,
                ["needs_auth", "--project-path", str(fake_project)],
                input="n\n",
            )

        # exit 0 because cancellation is a clean exit, not a failure.
        assert result.exit_code == 0, result.output
        mock_updater.add_component.assert_not_called()
        mock_updater.add_service.assert_not_called()
        mock_updater.add_plugin.assert_not_called()
        mock_updater.run_post_generation_tasks.assert_not_called()

    def test_unresolved_plugin_dep_aborts_with_pip_hint(
        self, fake_project: Path
    ) -> None:
        """A ``required_plugins`` entry whose package isn't pip-installed
        is unresolvable — the CLI should abort and tell the user to
        ``pip install aegis-stack-<name>``."""
        spec = PluginSpec(
            name="needs_base",
            kind=PluginKind.SERVICE,
            description="Plugin that depends on an uninstalled plugin",
            version="0.0.1",
            verified=False,
            required_plugins=["base"],  # base isn't in the registry
        )

        with (
            patch(
                "aegis.commands.add._resolve_plugin",
                return_value=(spec, "fake_module"),
            ),
            patch(
                "aegis.commands.add.validate_version_compatibility",
                return_value=None,
            ),
            # Block the resolver from finding ``base`` in the live
            # registry — discover_plugins() returns nothing extra.
            patch(
                "aegis.core.plugins.resolver.discover_plugins",
                return_value=[],
            ),
        ):
            result = runner.invoke(
                app,
                ["needs_base", "--project-path", str(fake_project), "--yes"],
            )

        assert result.exit_code == 1
        assert "pip install aegis-stack-base" in result.output
