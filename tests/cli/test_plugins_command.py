"""
Tests for ``aegis plugins`` (#769).

Covers:

* ``plugins list``  — in-tree section + external section, default order,
  compat status when invoked outside an Aegis project.
* ``plugins info`` — happy path metadata dump, missing-plugin error,
  in-project compat verdict.
* ``plugins search`` — registry-not-yet-available stub.
* In-tree-vs-external collision  — external plugin claiming an in-tree
  name is soft-skipped from discovery (covered by reusing
  ``plugin_discovery.discover_plugins`` with patched entry points).

There is intentionally no ``plugins install`` — putting bytes on disk is
``pip install``; project-configuration lives in ``aegis add`` (#771).

Tests use ``CliRunner`` against the ``plugins_app`` Typer app directly so
they don't depend on the module-level ``aegis.__main__:app`` state.
"""

from __future__ import annotations

from importlib.metadata import EntryPoint
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from aegis.commands.plugins import plugins_app
from aegis.core.plugins import discovery as plugin_discovery
from aegis.core.plugins.compat import CompatStatus, check_compat
from aegis.core.plugins.spec import PluginKind, PluginSpec

# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_discovery_cache() -> None:
    plugin_discovery.clear_cache()


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _make_external_spec(name: str = "scraper", version: str = "0.1.0") -> PluginSpec:
    return PluginSpec(
        name=name,
        kind=PluginKind.SERVICE,
        description=f"{name} plugin",
        version=version,
        verified=False,
        required_components=["backend"],
    )


def _patch_discovery(specs: list[PluginSpec]):
    """Patch discover_plugins to return ``specs`` directly (skips entry-point
    machinery — those tests live in test_plugin_discovery).

    Patches the symbol in ``aegis.commands.plugins`` rather than the source
    module: plugins.py imported ``discover_plugins`` into its own namespace
    at module load, so patching ``plugin_discovery.discover_plugins`` after
    the fact would leave plugins.py looking at the original. Also patch
    discover_plugin_cli_apps so info's CLI-mounted check doesn't accidentally
    enumerate real entry points.
    """
    cli_apps_patch = patch(
        "aegis.commands.plugins.discover_plugin_cli_apps",
        return_value={},
    )
    plugins_patch = patch(
        "aegis.commands.plugins.discover_plugins",
        return_value=specs,
    )

    class _Both:
        def __enter__(self) -> None:
            cli_apps_patch.start()
            plugins_patch.start()

        def __exit__(self, *args: object) -> None:
            plugins_patch.stop()
            cli_apps_patch.stop()

    return _Both()


# ---------------------------------------------------------------------
# `plugins list`
# ---------------------------------------------------------------------


class TestPluginsList:
    def test_list_includes_in_tree_section(self, runner: CliRunner) -> None:
        with _patch_discovery([]):
            result = runner.invoke(plugins_app, ["list"])
        assert result.exit_code == 0
        # In-tree section header + at least one in-tree spec.
        assert "In-tree" in result.stdout
        assert "auth" in result.stdout
        # No external section when there are no external plugins.
        assert "No external plugins installed" in result.stdout

    def test_list_includes_external_when_discovered(self, runner: CliRunner) -> None:
        ext = _make_external_spec("scraper")
        with _patch_discovery([ext]):
            result = runner.invoke(plugins_app, ["list"])
        assert result.exit_code == 0
        assert "External plugins" in result.stdout
        assert "scraper" in result.stdout

    def test_list_in_tree_first_external_after(self, runner: CliRunner) -> None:
        """Display order: in-tree first, external after, alphabetical within."""
        ext = _make_external_spec("scraper")
        with _patch_discovery([ext]):
            result = runner.invoke(plugins_app, ["list"])
        in_tree_idx = result.stdout.find("In-tree")
        external_idx = result.stdout.find("External plugins")
        assert in_tree_idx < external_idx

    def test_list_outside_project_marks_external_compat_as_unknown(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """When run outside an Aegis project, external plugins get the
        NOT_IN_PROJECT compat verdict in their status column."""
        ext = _make_external_spec("scraper")
        with (
            _patch_discovery([ext]),
            patch("aegis.commands.plugins._resolve_answers", return_value=None),
        ):
            result = runner.invoke(plugins_app, ["list"])
        assert result.exit_code == 0
        assert "scraper" in result.stdout
        assert "run with --project-path" in result.stdout

    def test_list_in_project_runs_compat_for_external(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """With a project context, external plugin status reflects compat."""
        ext = _make_external_spec("scraper")
        # Project lacks the required `backend` component.
        with (
            _patch_discovery([ext]),
            patch("aegis.commands.plugins._resolve_answers", return_value={}),
        ):
            result = runner.invoke(plugins_app, ["list"])
        assert result.exit_code == 0
        assert "scraper" in result.stdout
        assert "requires component" in result.stdout


# ---------------------------------------------------------------------
# `plugins info`
# ---------------------------------------------------------------------


class TestPluginsInfo:
    def test_info_in_tree_shows_first_party_badge(self, runner: CliRunner) -> None:
        result = runner.invoke(plugins_app, ["info", "auth"])
        assert result.exit_code == 0
        assert "first-party" in result.stdout
        assert "auth" in result.stdout

    def test_info_unknown_plugin_exits_nonzero(self, runner: CliRunner) -> None:
        with _patch_discovery([]):
            result = runner.invoke(plugins_app, ["info", "nope"])
        assert result.exit_code != 0
        assert "No plugin named" in result.stdout

    def test_info_external_plugin(self, runner: CliRunner) -> None:
        ext = _make_external_spec("scraper")
        with _patch_discovery([ext]):
            result = runner.invoke(plugins_app, ["info", "scraper"])
        assert result.exit_code == 0
        assert "scraper" in result.stdout
        # community + unverified call-out for non-in-tree, non-verified plugin.
        assert "community" in result.stdout

    def test_info_lists_options_when_present(self, runner: CliRunner) -> None:
        """auth has 3 options (level / engine / oauth); info should surface them."""
        result = runner.invoke(plugins_app, ["info", "auth"])
        assert result.exit_code == 0
        assert "Options" in result.stdout
        assert "level" in result.stdout
        assert "engine" in result.stdout

    def test_info_shows_migration_count(self, runner: CliRunner) -> None:
        result = runner.invoke(plugins_app, ["info", "auth"])
        assert result.exit_code == 0
        # auth declares 4 migrations (auth, auth_rbac, auth_org, auth_tokens).
        assert "Migrations: 4" in result.stdout

    def test_info_escapes_pyproject_extras(self, runner: CliRunner) -> None:
        """``python-jose[cryptography]`` must render as-is, not be eaten by Rich."""
        result = runner.invoke(plugins_app, ["info", "auth"])
        assert result.exit_code == 0
        assert "python-jose[cryptography]" in result.stdout


# ---------------------------------------------------------------------
# `plugins search`
# ---------------------------------------------------------------------


class TestPluginsSearch:
    def test_search_returns_stub_message(self, runner: CliRunner) -> None:
        result = runner.invoke(plugins_app, ["search", "anything"])
        assert result.exit_code == 0
        assert "not yet available" in result.stdout
        assert "pip install aegis-stack-<name>" in result.stdout

    def test_search_without_keyword_still_works(self, runner: CliRunner) -> None:
        result = runner.invoke(plugins_app, ["search"])
        assert result.exit_code == 0
        assert "not yet available" in result.stdout


# ---------------------------------------------------------------------
# In-tree-vs-external collision (#769 + #768)
# ---------------------------------------------------------------------


class TestInTreeCollision:
    """An external plugin claiming an in-tree name is silently dropped.

    This test exercises ``plugin_discovery.discover_plugins`` directly
    (not through plugins_app) since the collision check lives there.
    """

    def test_external_collides_with_in_tree(self, capsys) -> None:
        """A community package shipping ``name='auth'`` is rejected at
        discovery time so ``plugins list`` never shows it."""
        from aegis.core.plugins.discovery import (
            PLUGIN_ENTRY_POINT_GROUP,
            discover_plugins,
        )

        evil_spec = PluginSpec(
            name="auth",  # conflicts with in-tree auth service
            kind=PluginKind.SERVICE,
            description="evil",
        )
        ep = EntryPoint(name="auth", value="evil:get", group=PLUGIN_ENTRY_POINT_GROUP)

        with (
            patch.object(
                plugin_discovery,
                "_entry_points_for",
                side_effect=lambda group: [ep]
                if group == PLUGIN_ENTRY_POINT_GROUP
                else [],
            ),
            patch.object(EntryPoint, "load", return_value=lambda: evil_spec),
        ):
            result = discover_plugins()

        assert result == []
        err = capsys.readouterr().err
        assert "auth" in err
        assert "in-tree" in err


# ---------------------------------------------------------------------
# Compat helper sanity (covered separately but worth one integration test)
# ---------------------------------------------------------------------


class TestCheckCompatIntegration:
    """A handful of integration tests against real in-tree specs to
    guard the `info` / `list` consumers from drift in the compat helper.
    """

    def test_in_tree_auth_is_marked_in_tree(self) -> None:
        from aegis.core.services import SERVICES

        report = check_compat(SERVICES["auth"], {}, is_in_tree=True)
        assert report.status is CompatStatus.IN_TREE

    def test_external_with_no_project_returns_not_in_project(self) -> None:
        ext = _make_external_spec("scraper")
        report = check_compat(ext, None)
        assert report.status is CompatStatus.NOT_IN_PROJECT


# ---------------------------------------------------------------------
# Round-3 review fixes
# ---------------------------------------------------------------------


class TestResolveAnswersErrorHandling:
    """`_resolve_answers` must surface real errors but not break inspection.

    Round-3 fix: a corrupt or unreadable ``.copier-answers.yml`` previously
    fell into a bare ``except Exception`` and silently downgraded compat
    checks to ``NOT_IN_PROJECT``. We now warn to stderr and return None,
    so the rest of ``plugins list`` still runs.
    """

    def test_handles_corrupt_yaml_with_stderr_warning(
        self, tmp_path: Path, capsys
    ) -> None:
        from aegis.commands.plugins import _resolve_answers

        # YAML with a tab indent under a mapping key — invalid, parser raises.
        (tmp_path / ".copier-answers.yml").write_text(
            "_template_version: 0.6.11\n"
            "include_auth: true\n"
            "broken_block:\n"
            "\tkey: value\n"
        )
        result = _resolve_answers(tmp_path)
        assert result is None
        err = capsys.readouterr().err
        assert "Could not read" in err
        assert "Compat checks will be skipped" in err

    def test_missing_file_returns_none_silently(self, tmp_path: Path, capsys) -> None:
        from aegis.commands.plugins import _resolve_answers

        result = _resolve_answers(tmp_path)
        assert result is None
        # No noise on the absent-file path — that's the "not an Aegis
        # project" case, expected and silent.
        assert capsys.readouterr().err == ""


class TestPluginsListEscapesMarkup:
    """Round-3 fix: plugin-supplied ``[brackets]`` in name/description must
    not be parsed as Rich markup tags in the table output."""

    def test_list_escapes_brackets_in_description(self, runner: CliRunner) -> None:
        ext = PluginSpec(
            name="bracketsplugin",
            kind=PluginKind.SERVICE,
            description="ships [scary] markup tags",
            version="0.1.0",
            verified=False,
        )
        with _patch_discovery([ext]):
            result = runner.invoke(plugins_app, ["list", "--verbose"])
        assert result.exit_code == 0
        # Literal brackets render — they would have been dropped by Rich
        # before the escape was added.
        assert "[scary]" in result.stdout

    def test_info_escapes_brackets_in_description(self, runner: CliRunner) -> None:
        ext = PluginSpec(
            name="bracketsplugin",
            kind=PluginKind.SERVICE,
            description="ships [scary] markup tags",
            version="0.1.0",
            verified=False,
        )
        with _patch_discovery([ext]):
            result = runner.invoke(plugins_app, ["info", "bracketsplugin"])
        assert result.exit_code == 0
        assert "[scary]" in result.stdout


class TestInfoCliIndicatorRespectsReserved:
    """Round-3 fix: ``info``'s ``CLI: yes/no`` line must mirror the
    mount-time reserved-name filter, not the raw discovery."""

    def test_cli_indicator_says_no_when_collides_with_core_command(
        self, runner: CliRunner
    ) -> None:
        import typer as _typer

        ext = PluginSpec(
            name="init",  # collides with core `aegis init`
            kind=PluginKind.SERVICE,
            description="evil-twin",
            version="0.1.0",
            verified=False,
        )
        # Plugin claims a CLI sub-app, but mount-time filter would reject
        # it. info should reflect that.
        sub_app = _typer.Typer()

        with (
            _patch_discovery([ext]),
            patch(
                "aegis.commands.plugins.discover_plugin_cli_apps",
                # Mimic real behaviour: filter applies → init is rejected
                side_effect=lambda reserved_names=None: (
                    {}
                    if reserved_names and "init" in reserved_names
                    else {"init": sub_app}
                ),
            ),
        ):
            result = runner.invoke(plugins_app, ["info", "init"])
        assert result.exit_code == 0
        assert "CLI: no" in result.stdout
