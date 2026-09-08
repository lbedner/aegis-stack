"""
Tests for ``aegis.core.plugin_template_resolver``.

The resolver locates a plugin's ``templates/`` directory via
``importlib.resources``. Tests run against:

* ``tests.fixtures.aegis_plugin_test`` — the in-repo fake plugin that
  ships a minimal templates tree (covers the happy path).
* a stdlib package without templates (covers the "pure-code plugin"
  case where the resolver should return ``None``).
* a non-existent module (covers the import-error case).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from aegis.core.plugins.template_resolver import (
    TEMPLATE_SUBDIR,
    get_plugin_template_root,
)

# Make sure the fake plugin is on sys.path. ``tests/`` is added by
# pytest's rootdir machinery, but the fixture lives one level deeper
# under ``tests/fixtures/``.
TESTS_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
if str(TESTS_FIXTURES) not in sys.path:
    sys.path.insert(0, str(TESTS_FIXTURES))


class TestResolverHappyPath:
    def test_returns_path_to_templates_dir(self) -> None:
        root = get_plugin_template_root("aegis_plugin_test")
        assert root is not None
        assert root.is_dir()
        assert root.name == TEMPLATE_SUBDIR

    def test_resolved_root_contains_expected_jinja_file(self) -> None:
        """Smoke-check: the resolved tree has the per-service files we
        wrote in the fixture."""
        root = get_plugin_template_root("aegis_plugin_test")
        assert root is not None
        service_init = (
            root
            / "{{ project_slug }}"
            / "app"
            / "services"
            / "test_plugin"
            / "__init__.py.jinja"
        )
        assert service_init.is_file()


class TestResolverEdgeCases:
    def test_returns_none_for_pure_code_plugin(self) -> None:
        """Packages without a ``templates/`` subdirectory get ``None``
        (the "pure-code plugin" case — wiring data only, no files to
        ship)."""
        # ``json`` is a stdlib package and very definitely doesn't ship
        # a ``templates/`` subdirectory.
        assert get_plugin_template_root("json") is None

    def test_raises_modulenotfound_for_missing_package(self) -> None:
        with pytest.raises(ModuleNotFoundError):
            get_plugin_template_root("aegis_stack_definitely_not_installed")
