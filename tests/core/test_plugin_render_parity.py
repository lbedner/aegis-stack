"""
Render parity between the legacy ``{% if include_X %}`` path and the new
``{% for p in _plugins | default([]) %}`` path (round 8a foundation).

For each in-tree service, render the same shared template two ways and
assert the rendered byte content is identical:

    legacy:  {include_X: True,  _plugins: []}
    plugin:  {include_X: False, _plugins: [serialize_plugin_to_answer(SERVICES[X])]}

If the new for-loop emits the same imports / mounts as the existing
conditional blocks, the test passes byte-for-byte. If a regression is
introduced (a wiring entry dropped, an alias reordered, whitespace
drift), it will fail with a clear diff.

Round 8a starts with ``app/components/backend/api/routing.py`` only;
remaining shared templates are added as their plugin loops land.
"""

from __future__ import annotations

import pytest
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path
from aegis.core.plugins.composer import PLUGINS_ANSWER_KEY, serialize_plugin_to_answer
from aegis.core.services import SERVICES

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"


def _jinja_env() -> Environment:
    """Match the env constructed in ``ManualUpdater.__init__``."""
    return Environment(
        loader=FileSystemLoader(str(get_template_path())),
        trim_blocks=False,
        lstrip_blocks=False,
    )


def _render(template_rel_path: str, context: dict) -> str:
    env = _jinja_env()
    template = env.get_template(f"{PROJECT_SLUG_PLACEHOLDER}/{template_rel_path}.jinja")
    return template.render(context)


# Map each service name to the legacy ``include_*`` flag(s) it controls.
# Insights/payment/comms/ai all toggle a single flag; auth happens to
# share the file with three (auth/oauth/auth_org), but only ``include_auth``
# corresponds to "auth as a whole".
SERVICE_INCLUDE_KEY = {
    "auth": "include_auth",
    "ai": "include_ai",
    "blog": "include_blog",
    "comms": "include_comms",
    "insights": "include_insights",
    "payment": "include_payment",
}


@pytest.mark.parametrize("service_name", list(SERVICE_INCLUDE_KEY.keys()))
def test_routing_py_parity(service_name: str) -> None:
    """The legacy path and plugin path render byte-identical routing.py
    for every in-tree service, with all sub-feature flags at default.

    Default project state (memory backend, no oauth/voice/rag, ...) means
    only the unconditional router for each service should survive in
    both paths.
    """
    template = "app/components/backend/api/routing.py"
    spec = SERVICES[service_name]
    include_key = SERVICE_INCLUDE_KEY[service_name]

    defaults = get_copier_defaults()

    # Legacy: the include_X flag is on, no plugin entries.
    legacy_answers = {**defaults, include_key: True, PLUGINS_ANSWER_KEY: []}

    # Plugin: include_X flag is off, plugin entry carries the wiring.
    # serialize_plugin_to_answer applies ``when`` predicates against
    # the merged options dict (defaults here), so only entries that
    # match default project state survive.
    plugin_entry = serialize_plugin_to_answer(
        spec, plugin_options=None, project_answers=defaults
    )
    plugin_answers = {
        **defaults,
        include_key: False,
        PLUGINS_ANSWER_KEY: [plugin_entry],
    }

    legacy_output = _render(template, legacy_answers)
    plugin_output = _render(template, plugin_answers)

    assert legacy_output == plugin_output, (
        f"routing.py parity drift for {service_name}:\n"
        f"--- legacy ---\n{legacy_output}\n"
        f"--- plugin ---\n{plugin_output}\n"
    )


# ---------------------------------------------------------------------
# deps.py parity (auth slice, first of the per-service deps refactor)
#
# Today the shared ``deps.py.jinja`` defines per-service FastAPI
# dependency-provider functions inline behind ``{% if include_X %}``
# blocks (auth: 4 functions, payment: 1, insights: 3). The Option-1
# refactor moves each service's function bodies into its own
# ``app/services/<name>/deps.py`` and shrinks the shared template to
# imports + a ``{% for p in _plugins %}`` loop.
#
# This test pins parity for auth: rendering with ``include_auth=True``
# (legacy inline-function path) must equal rendering with
# ``_plugins=[serialize(SERVICES["auth"])]`` (per-service-file path).
# Initially fails because ``wiring.deps_providers`` for auth is not
# yet populated and the shared template has no plugin loop. Both
# come into existence in this refactor slice.
# ---------------------------------------------------------------------


DEPS_INCLUDE_KEY = {
    "auth": "include_auth",
    "blog": "include_blog",
    "insights": "include_insights",
    "payment": "include_payment",
}


@pytest.mark.parametrize("service_name", list(DEPS_INCLUDE_KEY.keys()))
def test_deps_py_parity(service_name: str) -> None:
    template = "app/components/backend/api/deps.py"
    spec = SERVICES[service_name]
    include_key = DEPS_INCLUDE_KEY[service_name]

    defaults = get_copier_defaults()
    # deps.py is gated on ``include_database`` at the top — both paths
    # render under the same project state so the database scaffolding
    # appears in both outputs.
    base = {**defaults, "include_database": True}

    legacy_answers = {**base, include_key: True, PLUGINS_ANSWER_KEY: []}
    plugin_entry = serialize_plugin_to_answer(
        spec, plugin_options=None, project_answers=base
    )
    plugin_answers = {
        **base,
        include_key: False,
        PLUGINS_ANSWER_KEY: [plugin_entry],
    }

    legacy_output = _render(template, legacy_answers)
    plugin_output = _render(template, plugin_answers)

    assert legacy_output == plugin_output, (
        f"deps.py parity drift for {service_name}:\n"
        f"--- legacy ---\n{legacy_output}\n"
        f"--- plugin ---\n{plugin_output}\n"
    )


# ---------------------------------------------------------------------
# Dashboard cards / modals __init__.py parity (all 5 in-tree services)
#
# These templates emit ``from <module> import <Symbol>`` plus the
# matching ``"<Symbol>"`` entry in ``__all__``. Wiring data on each
# spec's ``dashboard_cards`` / ``dashboard_modals`` already drives the
# new ``{% for p in _plugins %}`` loops; the legacy if-blocks were
# kept in absolute-import form so both paths emit byte-identical output.
# ---------------------------------------------------------------------


@pytest.mark.parametrize("service_name", list(SERVICE_INCLUDE_KEY.keys()))
def test_dashboard_cards_init_parity(service_name: str) -> None:
    template = "app/components/frontend/dashboard/cards/__init__.py"
    spec = SERVICES[service_name]
    include_key = SERVICE_INCLUDE_KEY[service_name]

    defaults = get_copier_defaults()
    legacy_answers = {**defaults, include_key: True, PLUGINS_ANSWER_KEY: []}
    plugin_entry = serialize_plugin_to_answer(
        spec, plugin_options=None, project_answers=defaults
    )
    plugin_answers = {
        **defaults,
        include_key: False,
        PLUGINS_ANSWER_KEY: [plugin_entry],
    }

    legacy_output = _render(template, legacy_answers)
    plugin_output = _render(template, plugin_answers)

    assert legacy_output == plugin_output, (
        f"cards/__init__.py parity drift for {service_name}:\n"
        f"--- legacy ---\n{legacy_output}\n"
        f"--- plugin ---\n{plugin_output}\n"
    )


@pytest.mark.parametrize("service_name", list(SERVICE_INCLUDE_KEY.keys()))
def test_dashboard_modals_init_parity(service_name: str) -> None:
    template = "app/components/frontend/dashboard/modals/__init__.py"
    spec = SERVICES[service_name]
    include_key = SERVICE_INCLUDE_KEY[service_name]

    defaults = get_copier_defaults()
    legacy_answers = {**defaults, include_key: True, PLUGINS_ANSWER_KEY: []}
    plugin_entry = serialize_plugin_to_answer(
        spec, plugin_options=None, project_answers=defaults
    )
    plugin_answers = {
        **defaults,
        include_key: False,
        PLUGINS_ANSWER_KEY: [plugin_entry],
    }

    legacy_output = _render(template, legacy_answers)
    plugin_output = _render(template, plugin_answers)

    assert legacy_output == plugin_output, (
        f"modals/__init__.py parity drift for {service_name}:\n"
        f"--- legacy ---\n{legacy_output}\n"
        f"--- plugin ---\n{plugin_output}\n"
    )


# ---------------------------------------------------------------------
# pyproject.toml parity (services with simple legacy deps blocks)
#
# Excluded: ``ai`` (deps are computed at render time from
# ``ai_framework`` + ``ai_providers`` — placeholder ``{AI_FRAMEWORK_DEPS}``
# in spec.pyproject_deps). ``insights`` (no legacy if-block in
# pyproject.toml.jinja today; httpx is satisfied transitively).
# ---------------------------------------------------------------------


PYPROJECT_DEPS_INCLUDE_KEY = {
    "auth": "include_auth",
    "blog": "include_blog",
    "comms": "include_comms",
    "payment": "include_payment",
}


@pytest.mark.parametrize("service_name", list(PYPROJECT_DEPS_INCLUDE_KEY.keys()))
def test_pyproject_deps_parity(service_name: str) -> None:
    """spec.pyproject_deps mirrors the legacy ``{%- if include_X %}``
    block bytes-for-bytes (same order, same version pins, same quoting).
    The plugin loop emits the same lines."""
    template = "pyproject.toml"
    spec = SERVICES[service_name]
    include_key = PYPROJECT_DEPS_INCLUDE_KEY[service_name]

    defaults = get_copier_defaults()
    legacy_answers = {**defaults, include_key: True, PLUGINS_ANSWER_KEY: []}
    plugin_entry = serialize_plugin_to_answer(
        spec, plugin_options=None, project_answers=defaults
    )
    plugin_answers = {
        **defaults,
        include_key: False,
        PLUGINS_ANSWER_KEY: [plugin_entry],
    }

    legacy_output = _render(template, legacy_answers)
    plugin_output = _render(template, plugin_answers)

    assert legacy_output == plugin_output, (
        f"pyproject.toml parity drift for {service_name}:\n"
        f"--- legacy ---\n{legacy_output}\n"
        f"--- plugin ---\n{plugin_output}\n"
    )


@pytest.mark.parametrize(
    "service_name",
    [
        # ``insights`` is excluded: ``card_utils.py`` carries an
        # insights-specific ``no_cache`` block in ``_open_modal`` that
        # evicts insights modals from the cache to load fresh data.
        # That's behaviour, not wiring — it lives outside the
        # ``{% for p in _plugins %}`` loop and produces a render-output
        # divergence between legacy and plugin paths for insights only.
        # Remaining services hit identical output via both paths.
        "auth",
        "ai",
        "blog",
        "comms",
        "payment",
    ],
)
def test_modal_registry_parity(service_name: str) -> None:
    """``modal_registry.py`` builds a ``modal_map`` keyed by component id.
    The plugin loop must emit the same imports + dict entries the legacy
    if-blocks do (in-tree wiring data carries the ``service_*`` modal ids
    the cards pass)."""
    template = "app/components/frontend/dashboard/modal_registry.py"
    spec = SERVICES[service_name]
    include_key = SERVICE_INCLUDE_KEY[service_name]

    defaults = get_copier_defaults()
    legacy_answers = {**defaults, include_key: True, PLUGINS_ANSWER_KEY: []}
    plugin_entry = serialize_plugin_to_answer(
        spec, plugin_options=None, project_answers=defaults
    )
    plugin_answers = {
        **defaults,
        include_key: False,
        PLUGINS_ANSWER_KEY: [plugin_entry],
    }

    legacy_output = _render(template, legacy_answers)
    plugin_output = _render(template, plugin_answers)

    assert legacy_output == plugin_output, (
        f"modal_registry.py parity drift for {service_name}:\n"
        f"--- legacy ---\n{legacy_output}\n"
        f"--- plugin ---\n{plugin_output}\n"
    )
