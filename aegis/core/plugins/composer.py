"""
Plugin composer — serialize ``PluginSpec`` instances into Copier answers.

Round 7 of the plugin system refactor (foundation for #770/#771).

The job: take a list of ``PluginSpec`` instances + a project-answers
context, and produce the ``_plugins`` list shape that Copier writes
into ``.copier-answers.yml``. Templates iterate that list with
``{% for p in plugins %}{% for r in p.wiring.routers %}…``.

Predicates declared on each wiring entry's ``when`` field are evaluated
*here*, at serialize time. Entries whose predicate returns ``False`` are
filtered out before writing the answers file. Templates therefore
iterate without per-entry conditional logic — the answers file is the
truth of "what got mounted".

Predicate input: a single dict that is the union of:
  * the plugin's parsed bracket-syntax options (e.g.
    ``{"engine": "playwright", "storage": "postgres"}``)
  * the project's ``.copier-answers.yml`` content (so wiring decisions
    can read broader project state like ``ai_backend`` or ``ollama_mode``).

Plugin options shadow project answers on key collision.

This module is data-only — no I/O, no Copier invocation. The caller
(``aegis add``, ticket #771) is responsible for reading and writing
the answers file and invoking Copier.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, fields, is_dataclass
from typing import Any

from .spec import (
    FrontendWidgetWiring,
    HealthCheckWiring,
    PluginSpec,
    PluginWiring,
    RouterWiring,
    SymbolWiring,
)

PLUGINS_ANSWER_KEY = "_plugins"
"""Key under which the serialized plugin list lives in
``.copier-answers.yml``. Underscore-prefixed because Copier treats
``_*`` keys as internal/private — they round-trip through the answers
file but aren't surfaced as user-facing prompts."""


def serialize_plugin_to_answer(
    spec: PluginSpec,
    plugin_options: dict[str, Any] | None = None,
    project_answers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render a single ``PluginSpec`` into the dict shape stored under
    ``_plugins[i]`` in ``.copier-answers.yml``.

    Per-entry ``when`` predicates are evaluated against ``opts``, the
    union of ``plugin_options`` (overriding) and ``project_answers``.
    Entries whose predicate returns ``False`` are dropped.

    Args:
        spec: the plugin spec to serialize.
        plugin_options: this plugin's parsed bracket-syntax options
            (e.g. the result of ``parse_options(spec_str, spec)``).
            Defaults to empty.
        project_answers: the project's existing copier answers, so
            predicates can gate on broader project state. Defaults
            to empty.

    Returns:
        A serializable dict containing the plugin's identity, options,
        and surviving wiring entries. Templates iterate this directly.
    """
    opts = dict(project_answers or {})
    opts.update(plugin_options or {})

    return {
        "name": spec.name,
        "version": spec.version,
        "verified": spec.verified,
        "options": dict(plugin_options or {}),
        # Packaging metadata — flat lists templates iterate to emit
        # pyproject.toml deps and docker-compose service blocks. Not
        # under ``wiring`` because these aren't injection-point hooks
        # (they don't have ``when`` predicates and don't need
        # serialize-time filtering); they're declarative packaging
        # data the plugin ships unconditionally.
        "pyproject_deps": list(spec.pyproject_deps),
        "docker_services": list(spec.docker_services),
        # CLI verb. When set, ``app/cli/main.py``'s plugin loop registers
        # ``app/cli/<cli_name>.py`` so ``<project> <cli_name> ...`` works
        # the same way the in-tree auth/llm subcommands do. Always present
        # (``None`` when unset) so templates can test it directly.
        "cli_name": spec.cli_name,
        "wiring": _serialize_wiring(spec.wiring, opts, spec.name),
    }


def serialize_plugins(
    specs: Iterable[PluginSpec],
    plugin_options_by_name: dict[str, dict[str, Any]] | None = None,
    project_answers: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Render a collection of ``PluginSpec``s into the ``_plugins`` list.

    Convenience wrapper over :func:`serialize_plugin_to_answer` for the
    common "serialize every active plugin" call site. ``plugin_options_by_name``
    maps plugin name to its parsed options; missing names get an empty
    options dict.
    """
    options_map = plugin_options_by_name or {}
    return [
        serialize_plugin_to_answer(
            spec,
            plugin_options=options_map.get(spec.name),
            project_answers=project_answers,
        )
        for spec in specs
    ]


# ---------------------------------------------------------------------
# Wiring → dict
# ---------------------------------------------------------------------


def _serialize_wiring(
    wiring: PluginWiring, opts: dict[str, Any], plugin_name: str
) -> dict[str, list[dict[str, Any]]]:
    """Filter + serialize each list of wiring entries against ``opts``.

    ``plugin_name`` is threaded through so that router entries with no
    explicit ``alias`` get one synthesized at serialize time (templates
    can then assume ``r.alias`` is always a non-null Python identifier).
    """
    return {
        "routers": [
            _normalize_router_dict(_entry_to_dict(e), plugin_name)
            for e in wiring.routers
            if _entry_keeps(e, opts)
        ],
        "dashboard_cards": [
            _entry_to_dict(e) for e in wiring.dashboard_cards if _entry_keeps(e, opts)
        ],
        "dashboard_modals": [
            _entry_to_dict(e) for e in wiring.dashboard_modals if _entry_keeps(e, opts)
        ],
        "settings_mixins": [
            _entry_to_dict(e) for e in wiring.settings_mixins if _entry_keeps(e, opts)
        ],
        "deps_providers": [
            _entry_to_dict(e) for e in wiring.deps_providers if _entry_keeps(e, opts)
        ],
        "health_checks": [
            _entry_to_dict(e) for e in wiring.health_checks if _entry_keeps(e, opts)
        ],
    }


def _normalize_router_dict(router: dict[str, Any], plugin_name: str) -> dict[str, Any]:
    """Guarantee ``router["alias"]`` is a non-null Python identifier.

    Plugin authors leave ``RouterWiring.alias`` unset for the common
    single-router case. Filling in ``f"{plugin_name}_{symbol}"`` here
    keeps the serialized payload self-contained: every shared template
    can render ``from M import S as {{ r.alias }}`` without a per-template
    ``or`` fallback (which would diverge across the 24 shared files).

    Multi-router plugins where two routers share a ``symbol`` must set
    ``alias`` explicitly — ``RouterWiring.alias``'s docstring spells
    that out, and any collision would be a plugin-author bug, not
    something this helper should paper over.
    """
    if router.get("alias"):
        return router
    router["alias"] = f"{plugin_name}_{router.get('symbol', 'router')}"
    return router


def _entry_keeps(entry: object, opts: dict[str, Any]) -> bool:
    """Apply the entry's ``when`` predicate; entries with no predicate
    always survive."""
    when = getattr(entry, "when", None)
    if when is None:
        return True
    try:
        return bool(when(opts))
    except Exception:
        # A misbehaving predicate shouldn't break the whole render;
        # treat exceptions as "predicate failed" and drop the entry.
        # The plugin author's tests should catch this, not the user.
        return False


def _entry_to_dict(entry: object) -> dict[str, Any]:
    """Serialise a single wiring entry, dropping the ``when`` callable
    (it's not JSON-serializable, and its decision has already been
    applied).

    The ``isinstance(entry, type)`` guard rejects dataclass *classes*
    (vs. instances) — ``is_dataclass()`` accepts both, but ``asdict()``
    requires an instance. Narrowing here keeps the type checker happy
    and surfaces a clear error if a caller misuses the helper.
    """
    if not is_dataclass(entry) or isinstance(entry, type):
        raise TypeError(
            f"expected dataclass instance wiring entry, got {type(entry).__name__}"
        )
    out = asdict(entry)
    out.pop("when", None)
    return out


# Re-exported for the small set of callers that introspect entry types
# (e.g. plugin authoring docs / scaffolding tools). Keeps the import
# surface predictable.
__all__ = [
    "PLUGINS_ANSWER_KEY",
    "FrontendWidgetWiring",
    "HealthCheckWiring",
    "RouterWiring",
    "SymbolWiring",
    "serialize_plugin_to_answer",
    "serialize_plugins",
]


# Silence unused-import lint without removing the re-exports.
_ = (fields,)
