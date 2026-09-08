"""
Plugin discovery via Python entry points.

Closes ticket #768 (plugin discovery) and lands R5 (CLI extension hook).
Both use the standard ``importlib.metadata`` entry-point mechanism, so
they share one module.

Two entry-point groups are recognised:

* ``aegis.plugins`` — each registered name resolves to a callable that
  returns a :class:`~aegis.core.plugin_spec.PluginSpec`. This is the
  primary plugin contract: declares files, options, migrations, etc.
  Loaded by :func:`discover_plugins`.

* ``aegis.plugins.cli`` — each registered name resolves to a
  :class:`typer.Typer` instance that gets mounted under
  ``aegis <plugin-name> ...``. Optional; a plugin can ship a ``PluginSpec``
  without a CLI sub-app and vice-versa. Loaded by
  :func:`discover_plugin_cli_apps`.

Discovery is **error-tolerant**: a malformed plugin must not break the
core CLI. Failures (import error, wrong return type, name collision) log
to stderr and skip the offending plugin. Both functions are cached at
module level — call :func:`clear_cache` from tests that mock entry points.

Example ``pyproject.toml`` for a third-party plugin::

    [project.entry-points."aegis.plugins"]
    scraper = "aegis_stack_scraper:get_spec"

    [project.entry-points."aegis.plugins.cli"]
    scraper = "aegis_stack_scraper.cli:app"
"""

from __future__ import annotations

import sys
from importlib.metadata import EntryPoint, entry_points
from typing import Any

from .spec import PluginSpec

PLUGIN_ENTRY_POINT_GROUP = "aegis.plugins"
"""Entry-point group name for plugin specs (#768)."""

PLUGIN_CLI_ENTRY_POINT_GROUP = "aegis.plugins.cli"
"""Entry-point group name for plugin CLI sub-apps (R5)."""


# ---------------------------------------------------------------------
# Module-level caches
# ---------------------------------------------------------------------

_DISCOVERED_PLUGINS: list[PluginSpec] | None = None
_DISCOVERED_CLI_APPS: dict[str, Any] | None = None


def clear_cache() -> None:
    """Reset both discovery caches.

    Used by tests that patch ``importlib.metadata.entry_points``. Not
    expected to be called in normal operation; entry points don't change
    while the CLI is running.
    """
    global _DISCOVERED_PLUGINS, _DISCOVERED_CLI_APPS
    _DISCOVERED_PLUGINS = None
    _DISCOVERED_CLI_APPS = None


# ---------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------


def _warn(message: str) -> None:
    """Write a discovery warning to stderr.

    Plugins are expected to be installed packages, so a malformed plugin
    is almost always an installation issue the user wants to know about
    (typo'd entry point, missing dependency, etc.). stderr keeps the
    message off any stdout machine-readable output.
    """
    print(f"[aegis] plugin discovery: {message}", file=sys.stderr)


# ---------------------------------------------------------------------
# #768 — discover plugin specs
# ---------------------------------------------------------------------


def discover_plugins() -> list[PluginSpec]:
    """Return every ``PluginSpec`` declared via the ``aegis.plugins``
    entry-point group.

    Order is the order entry points are returned by ``importlib.metadata``
    (typically install order, but treat as unspecified). Failures from a
    single plugin do not affect others.

    Caching: result is memoised at module level. Tests should call
    :func:`clear_cache` after patching ``entry_points``.

    In-tree-vs-external collision: an external plugin claiming a name
    already used by an in-tree service or component is rejected with a
    stderr warning and excluded from the result. The user keeps using
    the first-party feature; the third-party package is invisible to
    Aegis until renamed. Soft-skip rather than hard-error keeps a
    misnamed install from breaking the core CLI.
    """
    global _DISCOVERED_PLUGINS
    if _DISCOVERED_PLUGINS is not None:
        return list(_DISCOVERED_PLUGINS)

    in_tree_names = _in_tree_spec_names()

    discovered: list[PluginSpec] = []
    # plugin.name -> entry-point name that registered it. Used to make the
    # collision warning helpful ("plugin 'auth' from entry point 'foo'
    # collides with one from 'bar'"); not a distribution identifier
    # (importlib.metadata can give us the dist via ``ep.dist.name`` if we
    # ever need it, but the entry-point name is sufficient here).
    seen_names: dict[str, str] = {}

    for ep in _entry_points_for(PLUGIN_ENTRY_POINT_GROUP):
        spec = _load_plugin_spec(ep)
        if spec is None:
            continue

        if spec.name in in_tree_names:
            _warn(
                f"plugin {spec.name!r} declared by entry point {ep.name!r} "
                f"collides with an in-tree {in_tree_names[spec.name]}; "
                f"ignoring (rename the plugin to register it)."
            )
            continue

        # Name collisions across plugins are a real bug — two installed
        # packages competing for the same plugin name. First-registered
        # wins; we warn loudly on the second.
        prior = seen_names.get(spec.name)
        if prior is not None:
            _warn(
                f"plugin {spec.name!r} declared by entry point {ep.name!r} "
                f"collides with an existing plugin from {prior!r}; ignoring."
            )
            continue
        seen_names[spec.name] = ep.name
        discovered.append(spec)

    _DISCOVERED_PLUGINS = discovered
    return list(discovered)


def _in_tree_spec_names() -> dict[str, str]:
    """Return ``{name: 'service' | 'component'}`` for every in-tree spec.

    Lazy-imported to keep ``plugin_discovery`` from depending on the
    services/components registries at module load time (would create a
    cycle: services.py imports migration_generator which imports services).
    """
    from ..components import COMPONENTS
    from ..services import SERVICES

    out: dict[str, str] = {}
    for name in SERVICES:
        out[name] = "service"
    for name in COMPONENTS:
        out[name] = "component"
    return out


def _load_plugin_spec(ep: EntryPoint) -> PluginSpec | None:
    """Resolve one entry point to a ``PluginSpec``, or ``None`` on error."""
    try:
        loader = ep.load()
    except Exception as exc:  # pragma: no cover - import failure path
        _warn(f"failed to import {ep.value!r} for {ep.name!r}: {exc}")
        return None

    try:
        result = loader() if callable(loader) else loader
    except Exception as exc:  # pragma: no cover - get_spec() failure path
        _warn(f"calling {ep.value!r} for {ep.name!r} raised: {exc}")
        return None

    if not isinstance(result, PluginSpec):
        _warn(
            f"entry point {ep.name!r} ({ep.value!r}) returned "
            f"{type(result).__name__}, expected PluginSpec; ignoring."
        )
        return None
    return result


# ---------------------------------------------------------------------
# R5 — discover plugin CLI sub-apps
# ---------------------------------------------------------------------


def discover_plugin_cli_apps(
    reserved_names: set[str] | None = None,
) -> dict[str, Any]:
    """Return a mapping of ``plugin_name -> typer.Typer`` for every
    plugin declaring an entry point in ``aegis.plugins.cli``.

    Args:
        reserved_names: names already used by core commands (e.g. ``init``,
            ``add``, ``deploy``). Passed in by the caller — typically by
            inspecting the main Typer app's registered commands. A plugin
            CLI sub-app whose name collides with a reserved name is
            rejected with a stderr warning.

    Caching: only the **raw discovery** (the ``ep.name -> sub_app`` mapping)
    is cached at module level. Reserved-name filtering is applied on every
    call so different ``reserved_names`` between invocations honour the
    current set rather than returning a stale filtered view. Discovery is
    the slow step (entry-point enumeration + module imports); filtering is
    a dict scan, so this split costs nothing.
    """
    raw = _get_or_load_cli_apps()

    reserved = reserved_names or set()
    result: dict[str, Any] = {}
    for name, sub_app in raw.items():
        if name in reserved:
            _warn(
                f"CLI plugin {name!r} collides with a reserved core "
                f"command name; ignoring."
            )
            continue
        result[name] = sub_app
    return result


def _get_or_load_cli_apps() -> dict[str, Any]:
    """Lazily load + cache the raw ``ep.name -> typer.Typer`` mapping.

    Pulled out so the reserved-name filter in ``discover_plugin_cli_apps``
    operates on a stable cached set. ``clear_cache`` invalidates this.
    """
    global _DISCOVERED_CLI_APPS
    if _DISCOVERED_CLI_APPS is not None:
        return _DISCOVERED_CLI_APPS

    import typer  # imported lazily to keep cold-import cost off this module

    discovered: dict[str, Any] = {}
    for ep in _entry_points_for(PLUGIN_CLI_ENTRY_POINT_GROUP):
        sub_app = _load_plugin_cli(ep, typer.Typer)
        if sub_app is None:
            continue
        if ep.name in discovered:
            _warn(f"CLI plugin {ep.name!r} is registered twice; keeping the first.")
            continue
        discovered[ep.name] = sub_app

    _DISCOVERED_CLI_APPS = discovered
    return _DISCOVERED_CLI_APPS


def _load_plugin_cli(ep: EntryPoint, typer_class: type) -> Any | None:
    """Resolve one CLI entry point to a ``typer.Typer``, or ``None`` on error."""
    try:
        result = ep.load()
    except Exception as exc:  # pragma: no cover - import failure path
        _warn(f"failed to import CLI plugin {ep.value!r} for {ep.name!r}: {exc}")
        return None

    if not isinstance(result, typer_class):
        _warn(
            f"CLI entry point {ep.name!r} ({ep.value!r}) returned "
            f"{type(result).__name__}, expected typer.Typer; ignoring."
        )
        return None
    return result


# ---------------------------------------------------------------------
# Entry-point fetching (kept tiny so tests can patch the call site)
# ---------------------------------------------------------------------


def _entry_points_for(group: str) -> list[EntryPoint]:
    """Wrapper around ``importlib.metadata.entry_points`` for the group.

    ``entry_points()`` had a few API shapes across Python releases; this
    helper isolates the version we actually use (3.10+) and gives tests
    a single seam to patch via ``patch.object(plugin_discovery,
    '_entry_points_for', ...)``.
    """
    try:
        return list(entry_points(group=group))
    except Exception as exc:  # pragma: no cover - importlib failure
        _warn(f"failed to enumerate entry-point group {group!r}: {exc}")
        return []
