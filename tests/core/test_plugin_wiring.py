"""
Tests for plugin wiring (round 7 of plugin refactor).

Covers:

* The wiring dataclasses (``RouterWiring``, ``FrontendWidgetWiring``,
  ``SymbolWiring``, ``HealthCheckWiring``, ``PluginWiring``) — defaults,
  list-shape, optional ``when`` predicates.
* The serializer (``serialize_plugin_to_answer`` / ``serialize_plugins``)
  — predicate evaluation, JSON-serializability of output, exception
  tolerance in misbehaving predicates.
* Registry-shape sanity for in-tree services — auth/ai/blog/comms/insights/
  payment all have the expected number of routers/cards/modals after
  populating their wiring.

The big-picture round-trip test (in-tree service → plugin entry →
template render → identical output to the pre-existing Jinja conditional
path) lands in round 8 once the templates are extended.
"""

from __future__ import annotations

import json

import pytest

from aegis.core.plugins.composer import (
    PLUGINS_ANSWER_KEY,
    serialize_plugin_to_answer,
    serialize_plugins,
)
from aegis.core.plugins.spec import (
    FrontendWidgetWiring,
    HealthCheckWiring,
    PluginKind,
    PluginSpec,
    PluginWiring,
    RouterWiring,
    SymbolWiring,
)
from aegis.core.services import SERVICES

# ---------------------------------------------------------------------
# Dataclass shape
# ---------------------------------------------------------------------


class TestPluginWiringDefaults:
    def test_empty_wiring_has_all_empty_lists(self) -> None:
        w = PluginWiring()
        assert w.routers == []
        assert w.dashboard_cards == []
        assert w.dashboard_modals == []
        assert w.settings_mixins == []
        assert w.deps_providers == []
        assert w.health_checks == []

    def test_router_default_symbol_is_router(self) -> None:
        r = RouterWiring(module="m")
        assert r.symbol == "router"
        assert r.prefix == ""
        assert r.tags == []
        assert r.when is None

    def test_pluginspec_default_wiring(self) -> None:
        spec = PluginSpec(name="x", kind=PluginKind.SERVICE, description="")
        assert isinstance(spec.wiring, PluginWiring)
        assert spec.wiring.routers == []

    def test_independent_default_wiring_per_spec(self) -> None:
        """Default wirings must not be shared across PluginSpec instances."""
        a = PluginSpec(name="a", kind=PluginKind.SERVICE, description="")
        b = PluginSpec(name="b", kind=PluginKind.SERVICE, description="")
        a.wiring.routers.append(RouterWiring(module="x"))
        assert b.wiring.routers == []


# ---------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------


class TestSerializer:
    def _spec(self) -> PluginSpec:
        return PluginSpec(
            name="scraper",
            kind=PluginKind.SERVICE,
            description="x",
            version="0.1.0",
            verified=False,
            wiring=PluginWiring(
                routers=[
                    RouterWiring(module="api", symbol="router", prefix="/scraper"),
                    RouterWiring(
                        module="api.advanced",
                        symbol="router",
                        when=lambda opts: opts.get("engine") == "playwright",
                    ),
                ],
                dashboard_cards=[
                    FrontendWidgetWiring(module="f", symbol="ScraperCard"),
                ],
            ),
        )

    def test_basic_shape(self) -> None:
        result = serialize_plugin_to_answer(self._spec())
        assert result["name"] == "scraper"
        assert result["version"] == "0.1.0"
        assert result["verified"] is False
        assert "wiring" in result
        assert isinstance(result["wiring"]["routers"], list)

    def test_predicate_filters_routers(self) -> None:
        # No options → only the unconditional router survives.
        result = serialize_plugin_to_answer(self._spec())
        assert len(result["wiring"]["routers"]) == 1

        # engine=playwright → both survive.
        result = serialize_plugin_to_answer(
            self._spec(), plugin_options={"engine": "playwright"}
        )
        assert len(result["wiring"]["routers"]) == 2

        # engine=httpx → only the unconditional router.
        result = serialize_plugin_to_answer(
            self._spec(), plugin_options={"engine": "httpx"}
        )
        assert len(result["wiring"]["routers"]) == 1

    def test_plugin_options_shadow_project_answers(self) -> None:
        spec = PluginSpec(
            name="x",
            kind=PluginKind.SERVICE,
            description="",
            wiring=PluginWiring(
                routers=[
                    RouterWiring(
                        module="m",
                        when=lambda opts: opts.get("flag") is True,
                    ),
                ],
            ),
        )
        # Project says False, plugin options say True → plugin wins.
        result = serialize_plugin_to_answer(
            spec,
            plugin_options={"flag": True},
            project_answers={"flag": False},
        )
        assert len(result["wiring"]["routers"]) == 1

    def test_options_dict_is_copied_not_aliased(self) -> None:
        opts = {"engine": "playwright"}
        result = serialize_plugin_to_answer(self._spec(), plugin_options=opts)
        result["options"]["engine"] = "mutated"
        assert opts["engine"] == "playwright"

    def test_serialized_dict_is_json_safe(self) -> None:
        result = serialize_plugin_to_answer(self._spec())
        json.dumps(result)  # must not raise (no Callable left in payload)

    def test_when_callable_does_not_appear_in_output(self) -> None:
        result = serialize_plugin_to_answer(
            self._spec(), plugin_options={"engine": "playwright"}
        )
        for r in result["wiring"]["routers"]:
            assert "when" not in r

    def test_buggy_predicate_drops_entry(self) -> None:
        spec = PluginSpec(
            name="x",
            kind=PluginKind.SERVICE,
            description="",
            wiring=PluginWiring(
                routers=[
                    RouterWiring(module="ok"),
                    RouterWiring(
                        module="bad",
                        when=lambda opts: opts["nonexistent"]["attr"],  # KeyError
                    ),
                ],
            ),
        )
        result = serialize_plugin_to_answer(spec)
        # Only the well-behaved router survives; the buggy predicate
        # is treated as "filter out", not a crash.
        modules = [r["module"] for r in result["wiring"]["routers"]]
        assert modules == ["ok"]

    def test_serialize_plugins_collection(self) -> None:
        a = self._spec()
        b = PluginSpec(name="other", kind=PluginKind.SERVICE, description="")
        result = serialize_plugins([a, b])
        assert [p["name"] for p in result] == ["scraper", "other"]

    def test_alias_fallback_synthesized_when_unset(self) -> None:
        """Plugin authors leave alias unset for the common single-router
        case. The serializer fills in ``f'{plugin_name}_{symbol}'`` so
        templates can render ``r.alias`` without a fallback."""
        spec = PluginSpec(
            name="scraper",
            kind=PluginKind.SERVICE,
            description="",
            wiring=PluginWiring(
                routers=[
                    RouterWiring(module="aegis_plugin_scraper.api"),
                    RouterWiring(
                        module="aegis_plugin_scraper.admin",
                        symbol="admin_router",
                    ),
                ],
            ),
        )
        result = serialize_plugin_to_answer(spec)
        aliases = [r["alias"] for r in result["wiring"]["routers"]]
        # router 0: symbol defaulted to "router" → alias "scraper_router".
        # router 1: symbol "admin_router" → alias "scraper_admin_router".
        assert aliases == ["scraper_router", "scraper_admin_router"]

    def test_alias_explicit_value_preserved(self) -> None:
        """When the author sets ``alias`` explicitly, the serializer
        must not overwrite it (multi-router plugins where two routers
        share a ``symbol`` rely on this)."""
        spec = PluginSpec(
            name="scraper",
            kind=PluginKind.SERVICE,
            description="",
            wiring=PluginWiring(
                routers=[
                    RouterWiring(module="m", alias="custom_alias"),
                ],
            ),
        )
        result = serialize_plugin_to_answer(spec)
        assert result["wiring"]["routers"][0]["alias"] == "custom_alias"


# ---------------------------------------------------------------------
# Round-7 in-tree population sanity
# ---------------------------------------------------------------------


class TestInTreeWiringShape:
    """Pin the router/card/modal counts on each in-tree service so a
    future spec edit can't silently lose a wiring entry. Numbers below
    were computed by reading routing.py.jinja and the dashboard
    cards/modals __init__.py.jinja files."""

    @pytest.mark.parametrize(
        ("name", "routers", "cards", "modals"),
        [
            ("auth", 3, 1, 1),  # auth + oauth (gated) + org (gated)
            ("ai", 4, 1, 1),  # ai + voice + llm + rag (3 gated)
            ("blog", 1, 1, 1),
            ("comms", 1, 1, 1),
            ("insights", 1, 1, 1),
            ("payment", 2, 1, 1),  # router + pages
        ],
    )
    def test_wiring_counts(
        self, name: str, routers: int, cards: int, modals: int
    ) -> None:
        spec = SERVICES[name]
        assert len(spec.wiring.routers) == routers, name
        assert len(spec.wiring.dashboard_cards) == cards, name
        assert len(spec.wiring.dashboard_modals) == modals, name

    def test_auth_oauth_router_gated_off_by_default(self) -> None:
        result = serialize_plugin_to_answer(SERVICES["auth"])
        modules = [r["module"] for r in result["wiring"]["routers"]]
        assert "app.components.backend.api.auth.oauth" not in modules

    def test_auth_oauth_router_present_when_flag_set(self) -> None:
        result = serialize_plugin_to_answer(
            SERVICES["auth"],
            project_answers={"include_oauth": True},
        )
        modules = [r["module"] for r in result["wiring"]["routers"]]
        assert "app.components.backend.api.auth.oauth" in modules

    def test_ai_llm_router_requires_persistence_only(self) -> None:
        # The llm-router predicate reads ``ai_backend`` from the merged
        # opts dict. The catalog is provider-agnostic: the CLI ``llm``
        # command and the Cloud Catalog dashboard tab ship on every
        # persistence-backed stack, so the API they call must mount on
        # exactly the same condition — Ollama plays no part.
        result = serialize_plugin_to_answer(
            SERVICES["ai"],
            project_answers={"ai_backend": "memory", "ollama_mode": "none"},
        )
        modules = [r["module"] for r in result["wiring"]["routers"]]
        assert "app.components.backend.api.llm.router" not in modules

        # sqlite without ollama → llm router still mounts.
        result = serialize_plugin_to_answer(
            SERVICES["ai"],
            project_answers={"ai_backend": "sqlite", "ollama_mode": "none"},
        )
        modules = [r["module"] for r in result["wiring"]["routers"]]
        assert "app.components.backend.api.llm.router" in modules


# ---------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------


class TestConstants:
    def test_answers_key_is_plugins_with_underscore_prefix(self) -> None:
        # Underscore prefix tells Copier this is internal — round-trips
        # through the answers file but isn't surfaced as a user prompt.
        assert PLUGINS_ANSWER_KEY == "_plugins"


# ---------------------------------------------------------------------
# Re-export sanity
# ---------------------------------------------------------------------


def test_wiring_dataclasses_re_exported_from_composer() -> None:
    """Plugin authors can import wiring shapes from one module."""
    from aegis.core.plugins import composer as plugin_composer

    assert plugin_composer.FrontendWidgetWiring is FrontendWidgetWiring
    assert plugin_composer.HealthCheckWiring is HealthCheckWiring
    assert plugin_composer.RouterWiring is RouterWiring
    assert plugin_composer.SymbolWiring is SymbolWiring
