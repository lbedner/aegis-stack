"""Tests for ``get_all_owned_paths`` (RD-03 prerequisite, aegis-stack#918).

The render-diff engine (``aegis.core.render_diff``) must only ever act on
files that no component/service manifest claims — otherwise it creates,
overwrites or merges a component's own files in a project that never
selected that component.

Rather than hand-maintain a second list of "which paths are shared" (the
exact kind of list this initiative is removing), that boundary is derived
from data that already exists: every component/service already declares
its own file footprint via ``FileManifest``. A path is "owned" iff it
appears in some spec's ``FileManifest`` (any component, any service, any
extras group, directories expanded) via ``get_component_files(...,
full=True)``. Anything else is a shared-file candidate — this is what a
future ``ManualUpdater`` scopes the render-diff engine to (aegis-stack#919).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aegis.core.component_files import (
    get_all_owned_paths,
    get_component_files,
    get_shared_scope,
    get_template_path,
)
from aegis.core.components import COMPONENTS
from aegis.core.plugins.discovery import discover_plugins
from aegis.core.render_diff import RenderDiffEngine, build_template_env
from aegis.core.services import SERVICES


class TestGetAllOwnedPaths:
    def test_returns_a_set(self) -> None:
        assert isinstance(get_all_owned_paths(), set)

    def test_contains_a_known_component_exclusive_file(self) -> None:
        """scheduler/__init__.py belongs only to the scheduler component,
        has no cross-cutting content, and is never touched outside a
        scheduler add/remove — the textbook "owned" case."""
        owned = get_all_owned_paths()
        assert "app/components/scheduler/__init__.py" in owned

    def test_contains_worker_backend_variant_siblings(self) -> None:
        """All backend variants ship in the template tree simultaneously
        (Pattern D prunes them post-render) — every sibling must count as
        worker-owned, not just the eventually-chosen backend's files."""
        owned = get_all_owned_paths()
        for variant_file in (
            "app/components/worker/pools_dramatiq.py",
            "app/components/worker/pools_taskiq.py",
            "app/components/backend/api/worker_dramatiq.py",
        ):
            assert variant_file in owned, f"{variant_file} missing from owned set"

    def test_expands_directory_manifests_to_individual_files(self) -> None:
        """Some specs list a directory in ``primary`` rather than every
        file inside it (e.g. auth's orgs API); ownership must still cover
        the files, not just the directory string."""
        owned = get_all_owned_paths()
        assert "app/components/backend/api/auth/router.py" in owned

    def test_does_not_contain_known_shared_files(self) -> None:
        """Files with real cross-component conditional content — the
        textbook shared-file case — must never be claimed by any single
        spec's manifest, or the engine would wrongly skip regenerating
        them when handling a DIFFERENT component's add/remove."""
        owned = get_all_owned_paths()
        for shared_file in (
            "docker-compose.yml",
            "pyproject.toml",
            "app/core/config.py",
            "app/components/backend/api/deps.py",
            "app/components/backend/api/routing.py",
            "CLAUDE.md",
            "README.md",
            "Dockerfile",
        ):
            assert shared_file not in owned, f"{shared_file} unexpectedly owned"

    def test_every_spec_full_footprint_is_a_subset(self) -> None:
        """Sanity check on the derivation itself: nothing gets lost when
        every spec's footprint is unioned together."""
        owned = get_all_owned_paths()
        for name in (*COMPONENTS, *SERVICES):
            spec_files = set(get_component_files(name, full=True))
            missing = spec_files - owned
            assert not missing, f"{name}'s files dropped from the union: {missing}"


class TestGetSharedScope:
    """``get_shared_scope`` is the single canonical scoping expression a
    caller (``ManualUpdater``, aegis-stack#919) uses to restrict the
    render-diff engine — one function, not a duplicated exception list at
    every call site."""

    def test_unowned_path_is_in_scope(self) -> None:
        scope = get_shared_scope(
            ["docker-compose.yml", "app/components/scheduler/__init__.py"]
        )
        assert "docker-compose.yml" in scope

    def test_owned_path_is_excluded(self) -> None:
        scope = get_shared_scope(
            ["docker-compose.yml", "app/components/scheduler/__init__.py"]
        )
        assert "app/components/scheduler/__init__.py" not in scope

    def test_a_cross_cutting_owned_file_is_left_to_the_cross_spec_rule(
        self,
    ) -> None:
        """The scheduler's ``main.py`` depends on the worker's answers, but it
        is scheduler-owned: an unrelated operation must never create it.
        ``get_cross_spec_scope`` re-renders it where it exists."""
        scope = get_shared_scope(
            ["app/components/scheduler/main.py", "app/components/scheduler/__init__.py"]
        )
        assert "app/components/scheduler/main.py" not in scope

    def test_returns_a_sorted_list(self) -> None:
        scope = get_shared_scope(
            ["b.py", "a.py", "app/components/scheduler/__init__.py"]
        )
        assert scope == sorted(scope)

    def test_excludes_copier_owned_answers_file(self) -> None:
        """.copier-answers.yml.jinja references Copier's own runtime
        context (``_copier_conf``), which a bare Jinja render can't
        supply — unowned by any manifest, so the naive derivation would
        otherwise pull it into scope and crash on UndefinedError the
        first time the engine tries to render it."""
        scope = get_shared_scope(["docker-compose.yml", ".copier-answers.yml"])
        assert ".copier-answers.yml" not in scope
        assert "docker-compose.yml" in scope

    def test_excludes_the_migration_bootstraps_env(self) -> None:
        """alembic/env.py branches on the database engine, so the engine
        would create it in a project with no migrations the first time an
        add changes the engine; ``bootstrap_alembic`` owns whether it
        exists."""
        scope = get_shared_scope(["docker-compose.yml", "alembic/env.py"])
        assert "docker-compose.yml" in scope
        assert "alembic/env.py" not in scope


class TestPluginOwnedPathsStayOutOfEngineScope:
    """Plugin-owned files must never enter the render-diff engine's scope.

    ``get_all_owned_paths`` deliberately walks only ``COMPONENTS`` and
    ``SERVICES`` — installed plugins declare a ``FileManifest`` too, but
    they are NOT in the owned set. That is safe today for a second,
    independent reason: the engine's ``discover_paths()`` walks only
    aegis's OWN template tree, and a plugin's files come from the plugin
    package's tree, so they are never discovered in the first place.

    Two separate facts cancelling out is exactly the kind of thing that
    breaks silently when one side changes. If plugin template trees are
    ever overlaid into a single discovery pass (the natural shape if
    plugins gain their own extension points), plugin files become
    discovered-and-unowned — and the engine would start treating a
    plugin's vendored files as shared files it may backfill, overwrite,
    or 3-way merge. Plugin files are vendored artifacts owned by their
    plugin (``install_plugin_template_tree`` re-renders them wholesale on
    upgrade); the engine must never touch them.

    This pins the invariant so the failure is a loud test rather than
    silent data loss in someone's project.
    """

    def test_plugin_files_are_not_discovered_by_the_engine(self) -> None:
        template_root = get_template_path()
        engine = RenderDiffEngine(
            jinja_env=build_template_env(template_root),
            template_root=template_root,
            project_path=Path("/nonexistent"),
        )
        discovered = set(engine.discover_paths())

        assert not any(p.startswith("app/services/test_plugin/") for p in discovered), (
            "a plugin's files are discoverable by the engine — they must "
            "either be excluded from discovery or added to get_all_owned_paths"
        )

    def test_scope_would_reject_plugin_paths_if_they_were_ever_discovered(self) -> None:
        """The forward-looking half: today plugin paths are kept out by
        discovery alone, so ``get_shared_scope`` has never been asked
        about them. If plugin trees ever join discovery, this is the
        assertion that must be made to pass — by teaching
        ``get_all_owned_paths`` about installed plugins' manifests.

        Documented as an expected failure rather than asserted directly:
        making it pass today would mean adding plugin-awareness nothing
        currently needs. It exists so the requirement is written down and
        discoverable, not silently rediscovered later.
        """
        plugin_paths: set[str] = set()
        for spec in discover_plugins():
            manifest = getattr(spec, "files", None)
            if manifest is None:
                continue
            plugin_paths.update(manifest.primary)
            for group in manifest.extras.values():
                plugin_paths.update(group)

        if not plugin_paths:
            pytest.skip("no plugins installed in this environment")

        leaked = set(get_shared_scope(plugin_paths))
        assert leaked, (
            "get_all_owned_paths now recognizes plugin manifests — the "
            "companion invariant (plugin files stay out of engine scope) is "
            "no longer discovery-dependent. Flip this assertion to "
            "`assert not leaked` and update the class docstring."
        )
