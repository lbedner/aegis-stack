"""
Unified plugin specification — R2 of the plugin system refactor.

Replaces the parallel ``ServiceSpec`` / ``ComponentSpec`` types with a
single ``PluginSpec`` that covers in-tree services, in-tree components,
and (eventually) third-party plugins.

In-tree services and components are first-party plugins (``verified=True``);
external plugins use the same dataclass with ``verified=False``. The
``ServiceSpec`` and ``ComponentSpec`` aliases in
``aegis/core/services.py`` and ``aegis/core/components.py`` preserve
back-compat with pre-R2 call sites — they are subclasses of ``PluginSpec``
that pin ``kind`` to ``SERVICE`` / ``COMPONENT`` by default.

R2 keeps PluginKind narrow (``SERVICE`` / ``COMPONENT``). Additional
kinds (``INTEGRATION``, ``ENHANCEMENT``, ...) are added when a real
plugin needs them, not speculatively.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ..file_manifest import FileManifest


class PluginKind(Enum):
    """Top-level role a ``PluginSpec`` plays in an Aegis project."""

    SERVICE = "service"
    """Business-logic plugin (auth, payment, AI, scraping, ...)."""

    COMPONENT = "component"
    """Infrastructure plugin (database, redis, worker, frontend, ...)."""


# ---------------------------------------------------------------------
# PluginWiring — declarative injection-point hooks (round 7 of #770/#771)
# ---------------------------------------------------------------------
#
# Each shared template file (routing.py, deps.py, dashboard cards / modals,
# config.py settings, ...) iterates the project's plugins list with
# ``{% for entry in p.wiring.X %}`` to emit per-plugin imports + wiring
# calls. Each list field on ``PluginWiring`` is a list because plugins
# routinely have several mounts of the same kind: auth alone has three
# routers (auth_router always, oauth_router gated, org_router gated);
# payment has two; AI has up to four.
#
# Per-entry ``when`` predicate filters at serialize time. The ``_plugins``
# list written to ``.copier-answers.yml`` only contains entries whose
# ``when`` returned True; templates iterate without conditional logic.
#
# Predicate signature: ``(opts: dict) -> bool`` where ``opts`` is the
# plugin's parsed bracket-syntax options *merged with* the project's
# Copier answers. Plugin options shadow project answers on key collision.
# This lets a plugin gate on its own option (``opts["oauth"]``) or on
# broader project state (``opts["ollama_mode"]``) with the same API.
#
# In-tree services currently key their predicates off the legacy answer
# keys (``include_oauth``, ``ai_backend``, ``ai_voice``, ``ai_rag``, ...)
# rather than parsed-option names (``oauth``, ``backend``, ``voice``,
# ``rag``). That's deliberate: those keys live in ``.copier-answers.yml``
# from the existing ``aegis add-service`` flow, and the parity test is
# happy with them. When ``aegis add scraper[playwright]`` lands in
# round 8b, that command will normalise parsed option keys onto the
# corresponding answer keys before serialising, so predicates keep
# reading from a single namespace.


@dataclass
class RouterWiring:
    """How a plugin's FastAPI router is mounted in ``include_routers``."""

    module: str
    """Import path of the module exposing the router, e.g.
    ``"aegis_plugin_scraper.api"``."""

    symbol: str = "router"
    """Name of the ``APIRouter`` instance inside that module."""

    alias: str | None = None
    """Local alias used in the rendered ``from MODULE import SYMBOL as ALIAS``
    line, and as the bare name in ``app.include_router(ALIAS, ...)``. Required
    when a plugin has multiple routers that share a ``symbol`` (auth has 3,
    all with ``symbol=router``): the alias is what disambiguates them in the
    generated import block.

    If left ``None``, ``plugin_composer.serialize_plugin_to_answer`` fills
    in ``f"{plugin_name}_{symbol}"`` before the answers file is written,
    so templates can rely on the serialized ``alias`` always being a
    non-null Python identifier."""

    prefix: str = ""
    """URL prefix for ``app.include_router(prefix=...)``. Convention is
    ``"/api/v1"`` or ``"/api/v1/<plugin-name>"``."""

    tags: list[str] = field(default_factory=list)
    """OpenAPI tags applied to the mounted router."""

    when: Callable[[dict[str, Any]], bool] | None = None
    """Optional gate; see module-level note for predicate semantics."""


@dataclass
class FrontendWidgetWiring:
    """How a plugin's dashboard card or modal registers with the frontend."""

    module: str
    """Import path, e.g. ``"aegis_plugin_scraper.frontend"``."""

    symbol: str
    """Class name, e.g. ``"ScraperCard"`` or ``"ScraperModal"``."""

    modal_id: str | None = None
    """For cards: id of the modal this card opens (key into ``modal_map``).
    For modals: the id this modal is registered as. Pair card + modal by
    using the same ``modal_id`` on both."""

    when: Callable[[dict[str, Any]], bool] | None = None


@dataclass
class SymbolWiring:
    """Generic ``from MODULE import SYMBOL`` shape.

    Reused for several wiring kinds where the template only needs to
    know "import this name from this module" (settings mixins, FastAPI
    dependency providers, etc.).
    """

    module: str
    symbol: str
    when: Callable[[dict[str, Any]], bool] | None = None


@dataclass
class HealthCheckWiring:
    """How a plugin contributes a row to the dashboard health-check table."""

    module: str
    symbol: str
    label: str
    """Human-readable label shown in the dashboard health row."""

    when: Callable[[dict[str, Any]], bool] | None = None


@dataclass
class PluginWiring:
    """Optional injection-point hooks attached to a ``PluginSpec``.

    Every list defaults empty. A plugin not participating in a hook
    leaves the list empty; the corresponding template loop renders
    nothing.
    """

    routers: list[RouterWiring] = field(default_factory=list)
    """Backend FastAPI router mounts."""

    dashboard_cards: list[FrontendWidgetWiring] = field(default_factory=list)
    """Frontend dashboard cards."""

    dashboard_modals: list[FrontendWidgetWiring] = field(default_factory=list)
    """Frontend dashboard modals."""

    settings_mixins: list[SymbolWiring] = field(default_factory=list)
    """Pydantic settings mixin classes composed into the project's
    ``Settings`` model at class-definition time."""

    deps_providers: list[SymbolWiring] = field(default_factory=list)
    """FastAPI dependency provider modules (``Depends(...)`` callables)."""

    health_checks: list[HealthCheckWiring] = field(default_factory=list)
    """Dashboard health-check rows."""


@dataclass(kw_only=True)
class PluginSpec:
    """Unified specification for components, services, and third-party plugins.

    Field naming notes:

    * ``required_components`` / ``recommended_components`` / ``required_services``
      are the canonical dependency-list fields (matches the pre-R2
      ``ServiceSpec`` convention, which had the higher caller volume).
    * ``requires`` and ``recommends`` exist as **read-only** property aliases
      so legacy ``ComponentSpec``-style attribute access keeps working
      (``component.requires``, ``component.recommends``). Construction via
      those names is intentionally not supported — pass the canonical names.

    The ``type`` field is a sub-classification facet that is meaningful per
    ``kind``: when ``kind=SERVICE`` it carries a ``ServiceType`` (AUTH,
    PAYMENT, ...); when ``kind=COMPONENT`` it carries a ``ComponentType``
    (CORE, INFRASTRUCTURE). Typed as ``Any`` here to avoid a circular
    import; consumers narrow as needed.
    """

    # Identity
    name: str
    kind: PluginKind
    description: str

    # Longer, terminal-clean editorial copy (2-4 sentences) shown by the
    # guided init setup. Curated from each plugin's docs intro rather than
    # read from ``docs/`` at runtime: the wheel only ships the ``aegis``
    # package, and the markdown carries admonitions/links that don't render
    # in a terminal. Empty string degrades to ``description``.
    long_description: str = ""

    # Site-relative path of this plugin's documentation page (e.g.
    # ``components/worker``), joined onto the published docs base URL by
    # renderers that emit terminal hyperlinks. Empty string means the
    # plugin has no docs page yet — render no link rather than a dead one.
    # ``tests/core/test_spec_docs_paths.py`` pins every non-empty value to
    # a real source file under ``docs/``.
    docs_path: str = ""

    # Sub-classification — ServiceType when kind=SERVICE,
    # ComponentType when kind=COMPONENT.
    type: Any = None

    # Dependencies
    required_components: list[str] = field(default_factory=list)
    recommended_components: list[str] = field(default_factory=list)
    required_services: list[str] = field(default_factory=list)
    required_plugins: list[str] = field(default_factory=list)

    # Mutual exclusion
    conflicts: list[str] = field(default_factory=list)

    # Packaging / template
    pyproject_deps: list[str] = field(default_factory=list)
    docker_services: list[str] = field(default_factory=list)
    template_files: list[str] = field(default_factory=list)

    # File ownership for cleanup (R1)
    files: FileManifest = field(default_factory=FileManifest)

    # Project-relative path whose presence in a generated project means
    # "this plugin is installed". Drives ``aegis update``'s on-disk feature
    # detection (reconstructing ``include_*`` flags missing from older
    # ``.copier-answers.yml`` files) — see
    # ``aegis.commands.update._detect_existing_features``. Pick a path the
    # plugin unconditionally owns: a service's ``app/services/<name>``
    # directory, a component's primary module, or (when a plugin ships no
    # dedicated directory, like redis) one of its always-generated files.
    # Empty string means "not detectable from disk" (CORE components).
    marker_path: str = ""

    # Bracket-syntax options (R3) — see aegis/core/option_spec.py.
    # ``list[Any]`` rather than ``list[OptionSpec]`` to avoid a runtime
    # circular import; ``OptionSpec`` is only referenced by parsers.
    options: list[Any] = field(default_factory=list)

    # Database migrations (R4-A) — see aegis/core/migration_spec.py.
    # Each entry is a ``ServiceMigrationSpec`` declaring tables/columns
    # for the plugin. Typed as ``list[Any]`` to avoid a runtime cycle
    # (``migration_generator.py`` imports stay one-way).
    migrations: list[Any] = field(default_factory=list)

    # Injection-point hooks (round 7) — see PluginWiring above for the
    # declarative shapes consumed by template rendering and the composer.
    wiring: PluginWiring = field(default_factory=PluginWiring)

    # Post-render transform (RD-06, aegis-stack#921). Called with
    # ``(project_path, answers)`` once this plugin's files are on disk —
    # by ``post_gen_tasks.cleanup_components`` at init and by
    # ``ManualUpdater.add_component`` on the add path, so both produce
    # identical trees.
    #
    # The escape hatch for transforms that are not expressible as
    # declarative data. Everything a plugin contributes should be a file
    # list, a wiring entry, or an option — those compose, are
    # introspectable, and survive the render-diff engine. A *rename* is
    # the known exception: worker ships every backend's implementation
    # side by side (``pools_arq.py`` / ``pools_dramatiq.py`` /
    # ``pools_taskiq.py``) and selecting one means renaming it onto the
    # canonical ``pools.py`` and deleting the rest. No file list can say
    # that, and the render diff has no vocabulary for renames.
    #
    # Prefer declarative fields; reach for this only when the operation
    # genuinely isn't one. Hooks are invisible to the ownership
    # derivation (``get_all_owned_paths``) and to the engine, so a hook
    # that creates files outside the spec's ``FileManifest`` will confuse
    # both — keep transforms confined to paths the manifest already
    # claims.
    post_render: Callable[[Path, dict[str, Any]], None] | None = None

    # Answer keys to revert when this plugin is removed (RD-06). Keys that
    # only mean something while the plugin is installed — scheduler's
    # ``scheduler_backend`` / ``scheduler_with_persistence`` are the
    # in-tree case — would otherwise linger at their old values and leak
    # into later renders. Applied by
    # ``ManualUpdater._apply_removal_answer_resets``; empty for the
    # majority of specs, whose ``include_<name>`` flag is the only state
    # they own.
    reset_answers_on_remove: dict[str, Any] = field(default_factory=dict)

    # Plugin metadata
    version: str = "0.0.0"
    verified: bool = True

    # PEP 440 specifier string (e.g. ``">=0.6,<0.8"``) declaring which
    # aegis-stack CLI versions this plugin supports. Empty string means
    # "no constraint" — back-compat default for plugins that predate
    # #777. Validated by ``aegis.core.plugin_compat.check_aegis_version_compat``
    # at ``aegis add`` / ``aegis plugins update`` time; a mismatch warns
    # the user and aborts unless ``--force`` is passed.
    aegis_version: str = ""

    # CLI verb the plugin registers under in the generated project's typer
    # app, exactly as the user types it. When set, the plugin must ship a
    # module exposing a ``typer.Typer`` instance named ``app`` at
    # ``app/cli/<cli_name>.py``, with any hyphens replaced by underscores
    # (``web-scrape`` -> ``app/cli/web_scrape.py``), since hyphens are not
    # importable in a module path. The generated project's
    # ``app/cli/main.py`` plugin loop applies the same normalization when
    # it registers the module via ``app.add_typer(...)``, so the verb keeps
    # its hyphen on the command line. ``None`` means the plugin ships no
    # CLI surface. Decoupled from ``name`` so the install identifier
    # (``crawl4ai``) and the user-facing verb (``crawl``) can differ.
    cli_name: str | None = None

    # ----- Read-only legacy aliases -------------------------------------

    @property
    def requires(self) -> list[str]:
        """Component-style alias for ``required_components``."""
        return self.required_components

    @property
    def recommends(self) -> list[str]:
        """Component-style alias for ``recommended_components``."""
        return self.recommended_components


def required_names(
    spec: PluginSpec,
    *,
    exclude: Iterable[str] = (),
) -> list[str]:
    """This plugin's hard dependencies, for display ("Requires: ...").

    Order-stable, de-duplicated, bracket syntax stripped. ``exclude`` drops
    names that are uninformative in context (e.g. always-on CORE components
    like backend/frontend).
    """
    excluded = set(exclude) | {spec.name}
    seen: set[str] = set()
    out: list[str] = []
    for raw in [*spec.required_components, *spec.required_services]:
        base = raw.split("[", 1)[0]
        if base in excluded or base in seen:
            continue
        seen.add(base)
        out.append(base)
    return out


def pairs_well_with(
    spec: PluginSpec,
    registry: Iterable[PluginSpec],
    *,
    exclude: Iterable[str] = (),
) -> list[str]:
    """Names this plugin combines with, for display ("Pairs well with: ...").

    Order-stable and de-duplicated: the spec's own soft recommendations
    first, then the reverse direction (every plugin in ``registry`` that
    requires or recommends this one — that's what makes "database pairs
    with auth, payment, blog" derivable instead of hand-maintained). The
    spec's own hard dependencies are NOT pairings — they belong under
    "Requires:" via :func:`required_names`. ``exclude`` drops names that
    are uninformative in context (e.g. always-on CORE components).
    """
    excluded = set(exclude) | {spec.name} | set(required_names(spec))
    names = [*spec.recommended_components]
    for other in registry:
        if spec.name in (
            *other.required_components,
            *other.recommended_components,
            *other.required_services,
        ):
            names.append(other.name)

    seen: set[str] = set()
    out: list[str] = []
    for raw in names:
        base = raw.split("[", 1)[0]
        if base in excluded or base in seen:
            continue
        seen.add(base)
        out.append(base)
    return out
