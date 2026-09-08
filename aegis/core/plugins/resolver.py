"""
Forward plugin dependency resolution (#776).

When the user runs ``aegis add stripe``, stripe's spec may declare
``required_components=["database"]``, ``required_services=["auth"]``,
and ``required_plugins=["base"]``. Resolution walks those declarations
transitively and returns the ordered list of *missing* dependencies
the CLI must install before the target spec — plus any cycles or
unresolved external plugins surfaced as errors.

The reverse direction (what depends on X, used by ``aegis remove``)
lives in :mod:`aegis.core.plugin_compat`'s ``reverse_dependents``.

Design:

* The resolver is read-only — it never installs anything itself.
  The caller (``_install_plugin`` in ``aegis/commands/add.py``)
  decides whether to apply the plan, prompt the user, etc.
* "Missing" means "declared in ``required_*`` but not currently
  active in the project's ``.copier-answers.yml``." A spec that's
  already installed is silently skipped.
* External-plugin dependencies that aren't pip-installed surface
  as ``unresolved_plugins`` — the CLI tells the user to
  ``pip install aegis-stack-<name>`` and re-run. Auto-pip-install
  is intentionally out of scope: a network-side-effect from a
  ``configure`` verb is the wrong default.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from ..component_utils import extract_base_component_name
from ..components import COMPONENTS, CORE_COMPONENTS
from ..services import SERVICES
from .compat import _installed_plugins, _is_present, _plugin_name_only
from .discovery import discover_plugins
from .naming import dist_name
from .spec import PluginKind, PluginSpec


class CircularDependencyError(Exception):
    """A plugin's ``required_*`` chain cycles back to itself.

    Carries the cycle path so the CLI can show ``a → b → c → a`` rather
    than just naming the offending node.
    """

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        super().__init__(" → ".join(cycle))


class UnknownDependencyError(Exception):
    """A required service/component dep is not in the registry.

    In-tree services and components are always populated into the
    resolver registry, so a missing one indicates a typo or stale
    declaration on a spec — never a "user needs to pip install" case.
    Plugin-kind misses are tracked separately on
    ``ResolutionResult.unresolved_plugins`` so the CLI can tell the user
    which pip package to install.
    """


@dataclass(frozen=True)
class ResolvedDep:
    """One dependency the resolver wants the CLI to install."""

    name: str
    kind: PluginKind
    spec: PluginSpec


@dataclass
class ResolutionResult:
    """Output of :func:`resolve_dependencies`.

    ``to_install`` is the topologically-ordered list of deps the CLI
    should add *before* the target spec. ``unresolved_plugins`` lists
    plugin names declared as ``required_plugins`` that aren't currently
    discoverable (i.e. their pip package isn't installed) — the CLI
    surfaces those as errors so the user pip-installs them and retries.
    """

    to_install: list[ResolvedDep] = field(default_factory=list)
    unresolved_plugins: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.to_install and not self.unresolved_plugins


def _registry_view() -> dict[str, PluginSpec]:
    """Union of every spec the CLI knows about, keyed by name.

    Order: in-tree services + components first (deterministic), then
    discovered external plugins. ``discover_plugins`` already drops
    duplicates whose names collide with in-tree entries, so the dict
    write order doesn't shadow first-party specs.
    """
    out: dict[str, PluginSpec] = {}
    for spec in SERVICES.values():
        out[spec.name] = spec
    for spec in COMPONENTS.values():
        out[spec.name] = spec
    for spec in discover_plugins():
        out.setdefault(spec.name, spec)
    return out


def resolve_dependencies(
    target: PluginSpec,
    answers: dict[str, Any],
    registry: dict[str, PluginSpec] | None = None,
) -> ResolutionResult:
    """Compute the install plan for ``target`` against the project.

    Args:
        target: The plugin / service / component being added.
        answers: The project's ``.copier-answers.yml`` dict — used to
            decide whether each dep is already installed.
        registry: Override the spec lookup for tests. Defaults to the
            union of ``SERVICES`` + ``COMPONENTS`` + ``discover_plugins()``.

    Returns:
        :class:`ResolutionResult` with deps in topological order
        (deepest dep first, then its parents, then ``target`` is
        implicitly last — the caller installs ``target`` after working
        through ``to_install``).

    Raises:
        :class:`CircularDependencyError` when the dependency chain
        cycles. The cycle path is on the exception for the CLI to
        render.
    """
    reg = registry if registry is not None else _registry_view()
    plugins_present = _installed_plugins(answers)

    result = ResolutionResult()
    visited_globally: set[str] = set()
    # ``stack`` tracks the active recursion path so a back-edge during
    # DFS can be detected as a cycle (regular ``visited`` only catches
    # already-fully-resolved nodes, which is the correct DFS pattern).
    stack: list[str] = []

    def visit(spec: PluginSpec) -> None:
        if spec.name in stack:
            cycle_start = stack.index(spec.name)
            raise CircularDependencyError(stack[cycle_start:] + [spec.name])
        if spec.name in visited_globally:
            return
        stack.append(spec.name)

        # Walk all three dependency lists. Components and services are
        # in-tree specs (always in the registry). Plugins may be
        # external — if not yet pip-installed they go to
        # ``unresolved_plugins`` and the resolver continues with the
        # rest (the CLI summarises everything at once).
        for dep_constraint in spec.required_components:
            _resolve_one(
                dep_constraint,
                "component",
                reg,
                plugins_present,
                answers,
                result,
                visit,
            )
        for dep_constraint in spec.required_services:
            _resolve_one(
                dep_constraint, "service", reg, plugins_present, answers, result, visit
            )
        for dep_constraint in spec.required_plugins:
            _resolve_one(
                dep_constraint, "plugin", reg, plugins_present, answers, result, visit
            )

        stack.pop()
        visited_globally.add(spec.name)

    # ``target`` itself is intentionally NOT added to ``to_install``;
    # the caller already knows it's installing the target. We seed the
    # walk through ``visit(target)`` so the target's deps are explored
    # but the target is never re-added.
    visit(target)
    return result


def _resolve_one(
    dep_constraint: str,
    kind_hint: str,
    registry: dict[str, PluginSpec],
    plugins_present: set[str],
    answers: dict[str, Any],
    result: ResolutionResult,
    recurse: Any,
) -> None:
    """Process one entry from ``required_*``.

    Strips any version-constraint suffix (``"auth>=1.0"`` → ``"auth"``)
    AND any bracket-variant suffix (``"auth[org]"`` → ``"auth"``) so the
    registry lookup matches the base-name keys ``SERVICES``/``COMPONENTS``
    use. Variant-aware install (actually installing the ``[org]`` variant
    rather than the base) is intentionally out of scope here — the
    resolver canonicalises and the caller installs the base spec.

    With both suffixes stripped, decides whether the dep is:

    * already installed (skip),
    * known to the registry but missing from the project (queue for
      install + recurse for transitive deps),
    * a plugin name we have no spec for (record as unresolved and
      stop — can't recurse without a spec).
    """
    dep_name = _plugin_name_only(dep_constraint)
    # Collapse bracket variants AFTER version stripping. ``_is_present``
    # already canonicalises internally, but the registry lookup further
    # down keys on the bare name, so we have to canonicalise here too —
    # otherwise ``"auth[org]"`` falls through to ``UnknownDependencyError``
    # despite ``auth`` being in the registry.
    dep_name = extract_base_component_name(dep_name)
    if _is_present(dep_name, answers, plugins_present) or dep_name in CORE_COMPONENTS:
        return

    spec = registry.get(dep_name)
    if spec is None:
        # Plugin-kind misses are recoverable: tell the user to pip
        # install the package and re-run. Service/component misses are
        # not — those specs are seeded from in-tree registries that are
        # always present, so a miss is a typo or stale declaration on
        # the parent spec. Fail loud rather than silently no-op.
        if kind_hint == "plugin":
            if dep_name not in result.unresolved_plugins:
                result.unresolved_plugins.append(dep_name)
            return
        raise UnknownDependencyError(
            f"required {kind_hint} {dep_name!r} declared on a plugin "
            f"spec is not in the registry (typo or stale declaration?)"
        )

    # Recurse first so deepest-first ordering is preserved.
    recurse(spec)
    if not any(d.name == dep_name for d in result.to_install):
        result.to_install.append(ResolvedDep(name=dep_name, kind=spec.kind, spec=spec))


def format_plan(result: ResolutionResult, target_name: str) -> str:
    """Render a human-readable plan summary for the CLI to print.

    Empty plan returns an empty string. Otherwise output groups deps by
    kind and prints them in a stable ``Components → Services`` order so
    the rendered text is deterministic across resolutions. External
    plugins surface inside their declared kind (a plugin shipping a
    service spec lands under ``Services``); the bottom ``Missing pip
    packages`` line is reserved for plugin specs that aren't installed.
    """
    if result.is_empty:
        return ""

    lines: list[str] = [f"Installing {target_name!r} requires:"]
    by_kind: dict[PluginKind, list[str]] = {}
    for dep in result.to_install:
        by_kind.setdefault(dep.kind, []).append(dep.name)

    for kind in (PluginKind.COMPONENT, PluginKind.SERVICE):
        names = by_kind.get(kind)
        if names:
            label = kind.value.capitalize() + "s"
            lines.append(f"   {label}: {', '.join(names)}")

    if result.unresolved_plugins:
        lines.append(
            "   Missing pip packages: "
            + ", ".join(dist_name(n) for n in result.unresolved_plugins)
        )

    return "\n".join(lines)


def filter_installable(items: Iterable[ResolvedDep]) -> list[ResolvedDep]:
    """Filter to deps the caller can actually install via ManualUpdater.

    Today every spec the resolver returns is in-registry (since the
    out-of-registry path goes to ``unresolved_plugins``), so this is
    a passthrough — kept as an explicit hook for #780 (security
    validation) and #777 (version-compat) to layer in extra filtering
    without changing call sites.
    """
    return list(items)
