"""
Tests for ``aegis.commands.add._resolve_plugin``.

The internal helper that maps a user-facing ``spec_str`` (with or
without bracket options) to the ``(PluginSpec, module_name)`` pair the
rest of the install path needs. ``module_name`` matters for plugin
template resolution — it points at the on-disk package, not at the
spec's logical name (which can differ).

This file pins the entry-point handling shape parity with
``aegis.core.plugins.discovery._load_plugin_spec``: both factory
callables (``"pkg:get_spec"``) and pre-built instances (``"pkg:SPEC"``)
must resolve to the right module.
"""

from __future__ import annotations

from unittest.mock import patch

from aegis.commands.add import _resolve_plugin
from aegis.core.plugins.spec import PluginKind, PluginSpec


def _fake_spec(name: str = "scraper") -> PluginSpec:
    return PluginSpec(
        name=name,
        kind=PluginKind.SERVICE,
        description="fake",
        version="0.0.1",
        verified=False,
    )


class _FakeEntryPoint:
    """Minimal stand-in for ``importlib.metadata.EntryPoint``.

    We only use the three attributes ``_resolve_plugin`` reads
    (``name``, ``value``, ``load``); the real EntryPoint contract is
    larger but irrelevant here.
    """

    def __init__(self, name: str, value: str, load_returns) -> None:
        self.name = name
        self.value = value
        self._load_returns = load_returns

    def load(self):
        return self._load_returns


class TestResolvePluginEntryPointShape:
    def test_factory_callable_entry_point_resolves_module(self) -> None:
        """``scraper = "aegis_stack_scraper:get_spec"`` — load returns a
        callable, calling it returns the spec. Module name comes from
        the entry-point ``value`` (top-level package before the colon)."""
        spec = _fake_spec("scraper")

        def get_spec() -> PluginSpec:
            return spec

        ep = _FakeEntryPoint(
            "scraper",
            "aegis_stack_scraper.spec:get_spec",
            load_returns=get_spec,
        )
        with (
            patch("aegis.commands.add.discover_plugins", return_value=[spec]),
            patch(
                "aegis.commands.add.entry_points",
                return_value=[ep],
                create=True,
            ),
            patch("importlib.metadata.entry_points", return_value=[ep]),
        ):
            resolved = _resolve_plugin("scraper")

        assert resolved is not None
        plugin, module_name = resolved
        assert plugin.name == "scraper"
        # Module is the top-level package — derived from ep.value, not
        # plugin.name (which is the logical identifier).
        assert module_name == "aegis_stack_scraper"

    def test_instance_shape_entry_point_resolves_module(self) -> None:
        """``scraper = "aegis_stack_scraper:SPEC"`` — load returns the
        ``PluginSpec`` instance directly, NOT a callable. The previous
        implementation would call ``ep.load()()`` and crash inside the
        ``except``, falling through to ``plugin.name`` as the module
        name (wrong: ``scraper`` instead of ``aegis_stack_scraper``).
        Discovery handles both shapes; ``_resolve_plugin`` now mirrors
        that pattern."""
        spec = _fake_spec("scraper")

        ep = _FakeEntryPoint(
            "scraper",
            "aegis_stack_scraper.spec:SPEC",
            load_returns=spec,  # instance, NOT a callable
        )
        with (
            patch("aegis.commands.add.discover_plugins", return_value=[spec]),
            patch("importlib.metadata.entry_points", return_value=[ep]),
        ):
            resolved = _resolve_plugin("scraper")

        assert resolved is not None
        plugin, module_name = resolved
        assert plugin.name == "scraper"
        # Critical assertion: module name from ep.value, not the
        # plugin.name fallback. Pre-fix this would be ``"scraper"``.
        assert module_name == "aegis_stack_scraper"
