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

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ..file_manifest import FileManifest

# A Debian package name: what apt accepts, and nothing a shell or a line in
# ``docker/apt-packages.txt`` could reinterpret.
_APT_PACKAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")
# A script name under ``docker/build.d/``: no slashes, no shell metacharacters.
_DOCKER_STEP_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
# A queue name doubles as a module name under app/components/worker/queues/.
_QUEUE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
# The only two effects a tool may declare.
_AGENT_TOOL_EFFECTS = frozenset({"read", "writes"})


class PluginKind(Enum):
    """Top-level role a ``PluginSpec`` plays in an Aegis project."""

    SERVICE = "service"
    """Business-logic plugin (auth, payment, AI, scraping, ...)."""

    COMPONENT = "component"
    """Infrastructure plugin (database, redis, worker, frontend, ...)."""


class PartCategory(str, Enum):
    """The concern a part belongs to, the way Overseer groups the app:
    written into each generated project (``app/core/parts.py``)."""

    STACK = "stack"
    COMPUTE = "compute"
    DATA = "data"
    AI = "ai"
    APP = "app"
    PLATFORM = "platform"


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
    ``"aegis_stack_scraper.api"``."""

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
    """Import path, e.g. ``"aegis_stack_scraper.frontend"``."""

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


@dataclass(frozen=True)
class AgentToolWiring:
    """A tool a plugin registers, and the effect it has, declared.

    The declaration is the grant: a tool in the registry but not here is
    not given to the agent, and the project's own ``tests/core/test_tools``
    still fails it. The effect is a policy decision, never inferred from
    the function — ``read`` for a lookup, ``writes`` for anything that
    changes a row, and nothing in between.
    """

    name: str
    effect: str
    """``read`` or ``writes``."""

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
class OverseerPageWiring:
    """A page of the plugin's own on the htmx Overseer, at its entry in the
    rail, registered by ``overseer_sections`` as the in-tree pages are.
    Its partials, if any, are a ``RouterWiring`` whose router carries the
    Overseer gate (``overseer_access.overseer_gate``), gated on
    ``include_htmx`` with the page's files (``FileManifest.extras``)."""

    name: str
    """The entry it is the page of: the health check's label, the name
    the rail lists it under."""

    module: str
    """Import path of the module exposing ``SECTIONS`` and
    ``section_context``, e.g.
    ``"app.components.web_frontend.overseer_crawler"``."""

    folder: str
    """Its templates' folder, ``pages/overseer/<folder>/``."""

    group: str = "services"
    """The rail group it is listed in: ``services`` or ``components``."""

    when: Callable[[dict[str, Any]], bool] | None = None


@dataclass(frozen=True)
class WorkerQueueWiring:
    """A worker queue a plugin ships, and how its worker runs it.

    A bare name (``worker_queues=["crawler"]``) is the common case and keeps
    working; this carries the numbers a plugin needs to ship with its queue.
    Without it a queue falls back to ``WORKER_QUEUE_DEFAULT`` (10 jobs),
    which is wrong for work that pins a core: an ffmpeg conversion holding
    one of two vCPUs, ten times over, is an unresponsive box (issue #1870).
    """

    name: str
    # Jobs one worker process runs at once. None: keep the project default.
    concurrency: int | None = None
    # Seconds the oldest waiting job may sit before the queue reads as
    # backed up.
    max_wait_seconds: int | None = None


@dataclass
class ReadmeWiring:
    """What a plugin contributes to the generated project's README.

    The README used to carry one hand-written conditional per feature,
    which is how redis ended up guarded on ``include_cache`` (the answer
    key is ``include_redis``) and never rendered at all, and how finance,
    payment, documents and worker got no branch. Ownership moves here so
    a plugin's own lines arrive with the plugin.

    The narrative comes from the spec's ``description`` /
    ``long_description``; this carries only what those do not say.
    """

    reach: str = ""
    """Where the reader finds it: a port, a route, or a CLI group.
    Printed as the second column of the "What is running" table."""

    cli_groups: list[str] = field(default_factory=list)
    """Typer groups this plugin registers (``finance``, ``llm``)."""

    env_groups: list[str] = field(default_factory=list)
    """``.env.example`` group headings the Configuration section prints."""

    required_env: list[str] = field(default_factory=list)
    """Variables that gate startup, called out from the rest."""

    setup_notes: list[str] = field(default_factory=list)
    """Anything true before the first run: "Ollama is expected on the
    host". Rendered as comments under the ``cp .env.example .env`` line."""

    first_steps: list[str] = field(default_factory=list)
    """One or two things a new user actually does, for the "first ten
    minutes" section. Services only: a component is not something a
    reader opens."""


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

    overseer_pages: list[OverseerPageWiring] = field(default_factory=list)
    """Pages on the htmx Overseer: the web frontend's counterpart of a
    dashboard card and its modal."""

    settings_mixins: list[SymbolWiring] = field(default_factory=list)
    """Pydantic settings mixin classes composed into the project's
    ``Settings`` model at class-definition time."""

    deps_providers: list[SymbolWiring] = field(default_factory=list)
    """FastAPI dependency provider modules (``Depends(...)`` callables)."""

    health_checks: list[HealthCheckWiring] = field(default_factory=list)
    """Dashboard health-check rows."""

    agent_tools: list[AgentToolWiring] = field(default_factory=list)
    """Tools the plugin registers in its ``tools.py``, with their effect.

    Declaring one grants it to the default chat agent and to the MCP
    server; leaving it out is the deliberate "not for the agent" answer,
    not an oversight the framework should paper over."""


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

    The ``type`` field is a component's ``ComponentType`` (CORE,
    INFRASTRUCTURE, FRONTEND): whether it is always there. A service has
    none; what groups any part is its ``category``. Typed as ``Any`` here to
    avoid a circular import; consumers narrow as needed.
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

    # How the README and docs tables name the part (``catalog_docs``):
    # empty means its name, capitalised. Set only where that is wrong
    # (``htmx`` is the Web Frontend).
    title: str = ""

    # Site-relative path of this plugin's documentation page (e.g.
    # ``components/worker``), joined onto the published docs base URL by
    # renderers that emit terminal hyperlinks. Empty string means the
    # plugin has no docs page yet — render no link rather than a dead one.
    # ``tests/core/test_spec_docs_paths.py`` pins every non-empty value to
    # a real source file under ``docs/``.
    docs_path: str = ""

    # A component's ComponentType; None for a service.
    type: Any = None

    # The concern it belongs to (``PartCategory``), and the name the
    # generated app knows it by: its health check's, where that is not its
    # own (``redis`` is ``cache``). Written into every project as
    # ``app/core/parts.py`` by ``make parts`` (``aegis.core.parts``).
    category: PartCategory = PartCategory.APP
    health_name: str = ""

    # Where Overseer's map draws it, also written into ``parts.py``. ``tier``
    # is its row, a process of its own (0 the edge, 1 the app, 2 its data);
    # None runs inside the webserver; such a process's containers
    # (``docker_services``) show on its page. ``role`` is data's shape (``store``,
    # ``bucket``; empty: a box). ``depends_on`` are the parts it calls, by
    # health name, as the map's lines; ``consumes`` the ones it takes work
    # from (the worker, its queue). ``hosts``: what has no process of its
    # own runs in it (the backend). ``holds_keys``: every outside provider's
    # key lives in it (secrets). ``order`` places it, in the sidebar and in
    # its row; none: after the rest, by name.
    tier: int | None = None
    page: str = ""  # its Overseer page, where that is not its health name
    role: str = ""
    depends_on: list[str] = field(default_factory=list)
    consumes: list[str] = field(default_factory=list)
    hosts: bool = False
    holds_keys: bool = False
    order: int | None = None
    # Dev-only compose services that act on the developer's machine for
    # Overseer (deploy-agent): shown on its page and in its logs, never on
    # the map.
    agents: list[str] = field(default_factory=list)

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
    # System packages the plugin's image needs (``ffmpeg``,
    # ``poppler-utils``). The template's Dockerfile installs them from
    # ``docker/apt-packages.txt``, a data file assembled from every active
    # plugin's list — so a plugin never edits the Dockerfile itself.
    # Validated as Debian package names at construction.
    docker_packages: list[str] = field(default_factory=list)
    # Build steps the plugin ships as ``docker/build.d/<name>.sh``
    # scripts (tarball downloads, model fetches). The template's build hook
    # runs them in name order. A name, not a command: reviewable in the
    # diff, manifest-owned, and never interpolated into a shell.
    docker_steps: list[str] = field(default_factory=list)
    # Worker queues the plugin ships: each has a module at
    # ``app/components/worker/queues/<name>.py`` in its templates, and a
    # stack with the worker component runs a ``worker-<name>`` container
    # for it (one process). Without the component the queue is only a file.
    # A bare name is enough; a ``WorkerQueueWiring`` also ships the
    # queue's concurrency and backup threshold.
    worker_queues: list[str | WorkerQueueWiring] = field(default_factory=list)
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

    readme: ReadmeWiring = field(default_factory=ReadmeWiring)
    """The plugin's own lines in the generated README."""

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
    # ``scheduler_backend`` is the
    # in-tree case — would otherwise linger at their old values and leak
    # into later renders. Applied by
    # ``ManualUpdater._apply_removal_answer_resets``; empty for the
    # majority of specs, whose ``include_<name>`` flag is the only state
    # they own.
    reset_answers_on_remove: dict[str, Any] = field(default_factory=dict)

    # Plugin metadata
    version: str = "0.0.0"
    verified: bool = True
    # Schema, APIs and CLI surface may change between releases. A field, not
    # a word in ``description``: listings and the init wizard badge it, and
    # ``add-service`` warns once. Never a confirmation prompt.
    experimental: bool = False

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
    # ``app/cli/main.py`` applies the same normalization when it lists the
    # module in its ``GROUPS`` (loaded when run), so the verb keeps its
    # hyphen on the command line. ``None`` means the plugin ships no
    # CLI surface. Decoupled from ``name`` so the install identifier
    # (``crawl4ai``) and the user-facing verb (``crawl``) can differ.
    cli_name: str | None = None

    def __post_init__(self) -> None:
        """Refuse names that cannot be safe in the Dockerfile's shell.

        ``docker_packages`` land in ``xargs`` (never a shell), and
        ``docker_steps`` name files under ``docker/build.d/`` — but a name
        with whitespace or a quote still breaks a filename or a line in
        the data file. Validate at construction so a plugin author sees it
        at import time, not in a failed image build.
        """
        for package in self.docker_packages:
            if not _APT_PACKAGE_NAME.match(package):
                raise ValueError(
                    f"{self.name}: docker_packages entry {package!r} is not a "
                    "Debian package name (expected [a-z0-9][a-z0-9+.-]*)"
                )
        for queue in self.worker_queues:
            name = queue if isinstance(queue, str) else queue.name
            if not _QUEUE_NAME.match(name):
                raise ValueError(
                    f"{self.name}: worker queue {name!r} is not a queue name "
                    "(expected [a-z][a-z0-9_]*)"
                )
            if isinstance(queue, WorkerQueueWiring):
                numbers = (queue.concurrency, queue.max_wait_seconds)
                if any(number is not None and number <= 0 for number in numbers):
                    raise ValueError(
                        f"{self.name}: queue {name!r} needs positive numbers, got "
                        f"concurrency={queue.concurrency}, "
                        f"max_wait_seconds={queue.max_wait_seconds}"
                    )
        for tool in self.wiring.agent_tools:
            if tool.effect not in _AGENT_TOOL_EFFECTS:
                raise ValueError(
                    f"{self.name}: agent tool {tool.name!r} declares effect "
                    f"{tool.effect!r}; expected one of "
                    f"{sorted(_AGENT_TOOL_EFFECTS)}"
                )
        for step in self.docker_steps:
            if not _DOCKER_STEP_NAME.match(step):
                raise ValueError(
                    f"{self.name}: docker_steps entry {step!r} is not a script "
                    "name (expected [a-z0-9][a-z0-9_-]*)"
                )

    # ----- Read-only legacy aliases -------------------------------------

    @property
    def worker_queue_names(self) -> list[str]:
        """The queue names, whether declared bare or as a wiring."""
        return [
            queue if isinstance(queue, str) else queue.name
            for queue in self.worker_queues
        ]

    @property
    def display_title(self) -> str:
        """How the docs tables and the CLI's questions name the part: its
        ``title``, else its name, capitalised."""
        return self.title or self.name.capitalize()

    @property
    def app_name(self) -> str:
        """The name the generated app knows it by (``health_name``, else
        its own)."""
        return self.health_name or self.name

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
