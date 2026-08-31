"""``aegis add <plugin>`` must wire the plugin into shared files.

RD-05 (aegis-stack#920). Shared templates iterate the project's plugin
list (``{% for p in _plugins %}``) to emit each plugin's pyproject deps,
routers, dashboard cards, settings, and health checks. Installing a
plugin therefore has to regenerate those shared files with the plugin
present, exactly like adding a component or service does.

``add_plugin`` persists answers via ``_save_answers`` BEFORE calling
``_regenerate_shared_files``, and ``_save_answers`` rebinds
``self.answers`` to the very dict it was handed. The regen then renders
its BASE (the pre-operation baseline) and its OURS (the post-operation
target) from what is now the *same object* — so every file compares
equal to itself, nothing is classified as changed, and the plugin's
wiring never reaches the project. ``remove_plugin`` and
``remove_component`` deliberately regenerate BEFORE persisting for this
exact reason (issue #869); ``add_plugin`` is the one path that doesn't.

The existing plugin suites never caught this: they monkeypatch
``_regenerate_shared_files`` out entirely (synthetic fixture projects
have no shared template files to regenerate), so the only assertion
about it is that it was called.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from aegis.core.file_manifest import FileManifest
from aegis.core.manual_updater import ManualUpdater
from aegis.core.plugins.spec import PluginKind, PluginSpec
from tests.cli.conftest import ProjectFactory

TESTS_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
if str(TESTS_FIXTURES) not in sys.path:
    sys.path.insert(0, str(TESTS_FIXTURES))

# Regen shells out to ruff/git per file — same serialization rationale as
# the sibling #715 / #814 suites.
pytestmark = pytest.mark.xdist_group("generated_stacks")

MARKER_DEP = "aegis-plugin-marker-dep>=9.9.9"


def _spec_with_dep() -> PluginSpec:
    """A plugin whose only footprint is one pyproject dependency.

    ``pyproject.toml.jinja`` renders ``p.pyproject_deps`` for every entry
    in ``_plugins``, so the dep appearing in the project's pyproject is a
    direct, unambiguous signal that shared-file regen ran with the plugin
    in the answers.
    """
    return PluginSpec(
        name="marker_plugin",
        kind=PluginKind.SERVICE,
        description="Test plugin contributing a pyproject dep.",
        version="0.0.1",
        verified=False,
        pyproject_deps=[MARKER_DEP],
        files=FileManifest(),
    )


class TestAddPluginRegeneratesSharedFiles:
    def test_plugin_pyproject_dep_reaches_the_project(
        self, project_factory: ProjectFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            ManualUpdater, "run_post_generation_tasks", lambda self: None
        )
        project = project_factory("base")
        pyproject = project / "pyproject.toml"
        assert MARKER_DEP not in pyproject.read_text()

        updater = ManualUpdater(project)
        result = updater.add_plugin(
            spec=_spec_with_dep(),
            plugin_module_name="aegis_plugin_test",
            run_post_gen=False,
        )

        assert result.success, result.error_message
        assert MARKER_DEP in pyproject.read_text(), (
            "add_plugin did not regenerate pyproject.toml with the plugin's "
            "dependency — shared-file regen saw identical BASE and OURS "
            "because answers were persisted before it ran"
        )

    def test_regen_reports_the_changed_shared_file(
        self, project_factory: ProjectFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The UpdateResult must name pyproject.toml, so ``aegis add``'s
        output reflects what actually changed."""
        monkeypatch.setattr(
            ManualUpdater, "run_post_generation_tasks", lambda self: None
        )
        project = project_factory("base")

        updater = ManualUpdater(project)
        result = updater.add_plugin(
            spec=_spec_with_dep(),
            plugin_module_name="aegis_plugin_test",
            run_post_gen=False,
        )

        assert result.success, result.error_message
        assert "pyproject.toml" in result.shared_files_updated


class TestAddPluginAnswersStillPersisted:
    """Fixing the ordering must not lose the persistence guarantee the
    original ordering was protecting: the plugin entry has to be on disk
    when add_plugin returns, since the resolver flow builds a fresh
    ManualUpdater per install and reads answers back from disk."""

    def test_plugin_entry_is_on_disk_after_add(
        self, project_factory: ProjectFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            ManualUpdater, "run_post_generation_tasks", lambda self: None
        )
        project = project_factory("base")

        updater = ManualUpdater(project)
        result = updater.add_plugin(
            spec=_spec_with_dep(),
            plugin_module_name="aegis_plugin_test",
            run_post_gen=False,
        )
        assert result.success, result.error_message

        # A *fresh* updater reads answers from disk — the resolver flow's
        # actual access pattern.
        reloaded = ManualUpdater(project)
        assert any(
            p.get("name") == "marker_plugin"
            for p in (reloaded.answers.get("_plugins") or [])
        ), "plugin entry was not persisted to .copier-answers.yml"
