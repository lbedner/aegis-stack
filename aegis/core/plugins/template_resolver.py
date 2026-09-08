"""
Locate a plugin's template tree on disk.

Convention: every plugin package ships a ``templates/`` subdirectory
laid out the same way as aegis-stack's own
``aegis/templates/copier-aegis-project/{{ project_slug }}/...``.
Standard Python packaging picks the directory up automatically (both
hatchling and setuptools include non-Python files under the package
root by default), so plugin authors don't need any extra config beyond
shipping the files.

This resolver returns the on-disk path to a plugin's
``<package>/templates/`` directory, or ``None`` if the plugin doesn't
ship templates (some plugins are pure code — CLI hooks, dependency
providers, etc. — and contribute via wiring data alone).

Lookup uses ``importlib.resources`` and supports filesystem-backed
plugin installs:

* installed packages (``pip install aegis-stack-scraper``)
* development editable installs (``pip install -e .``)

Zipped wheels are **not** supported today — the caller
(``ManualUpdater.install_plugin_template_tree``) walks the resolved
directory with ``Path.rglob`` and renders through ``FileSystemLoader``,
both of which require a real on-disk path. Adding zip-wheel support is
straightforward (use ``importlib.resources.as_file`` as a context
manager and keep it alive for the duration of the render) but is
deferred until a real plugin ships as a non-editable wheel.

The caller — ``ManualUpdater`` and round 8b's ``aegis add`` — iterates
the resolved tree, renders each ``*.jinja`` through the same Jinja2
environment used for the project's own templates, and writes the
result into the target project at the corresponding relative path.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

TEMPLATE_SUBDIR = "templates"
"""Directory name plugins must use for their template tree.

Hardcoded — keeping this a convention rather than a configurable per-plugin
setting means tooling can locate plugin templates without first reading
plugin metadata."""


def get_plugin_template_root(plugin_module_name: str) -> Path | None:
    """Return the on-disk path to a plugin's ``templates/`` directory.

    Args:
        plugin_module_name: Top-level module name of the plugin package
            (e.g. ``"aegis_stack_scraper"``). Must be importable.

    Returns:
        Path to the templates directory if the package has one, else
        ``None``. The path may point at a real filesystem location (for
        editable installs) or a temporary materialized directory (for
        zipped wheels) — callers should treat it as read-only.

    Raises:
        ModuleNotFoundError: if the plugin package isn't installed.
    """
    # ``files()`` returns a Traversable rooted at the package; joinpath
    # then names the templates subdir. We don't ``as_file()`` here
    # because callers iterate the tree with ``rglob``/``walk`` and
    # construct individual file paths — staying at the Traversable
    # layer keeps that working for both filesystem and zipfile cases.
    pkg_root = resources.files(plugin_module_name)
    templates = pkg_root / TEMPLATE_SUBDIR

    # ``Traversable.is_dir()`` works for both filesystem and zip-backed
    # resources. We bail out early when the directory simply isn't there
    # — that's the "pure-code plugin" case, not an error.
    if not templates.is_dir():
        return None

    # Filesystem installs only (see module docstring): the Traversable's
    # ``__fspath__`` IS a real path on disk for both ``pip install`` and
    # ``pip install -e .``. For zipped wheels the str() would point inside
    # the zip and ``rglob`` downstream would fail — that case is out of
    # scope until a real plugin ships zipped, at which point we'd switch
    # to ``importlib.resources.as_file`` with a context manager that
    # stays open across the iteration.
    return Path(str(templates))
