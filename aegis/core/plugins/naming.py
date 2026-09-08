"""The one place the plugin package prefix is spelled.

A plugin named ``crawl4ai`` ships as the distribution ``aegis-stack-crawl4ai``
with the import package ``aegis_stack_crawl4ai``. Why this prefix:
docs/plugins.md, "Naming". Everything that builds either name (the
scaffold and its templates, install hints, the resolver's missing-package
list) goes through here; ``tests/core/test_plugin_naming.py`` guards it.
"""

DIST_PREFIX = "aegis-stack-"
"""PyPI distribution prefix: ``pip install aegis-stack-<name>``."""

PACKAGE_PREFIX = "aegis_stack_"
"""Import package prefix: ``import aegis_stack_<name>``."""


def dist_name(name: str) -> str:
    """The PyPI distribution for plugin ``name``."""
    return f"{DIST_PREFIX}{name}"


def package_name(name: str) -> str:
    """The import package for plugin ``name``."""
    return f"{PACKAGE_PREFIX}{name}"
