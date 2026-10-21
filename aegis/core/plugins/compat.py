"""
Plugin compatibility checking against the current project.

Used by ``aegis plugins list`` and ``aegis plugins info`` (#769) to tell
the user whether a discovered plugin can be added to their project, and
why not if it can't.

Checks declared on each ``PluginSpec`` against the project's
``.copier-answers.yml`` (which records the components/services already
included, and the list of installed plugins). Strictly read-only — no
side effects on the project.

Plugin-version compatibility against the running Aegis CLI version
(e.g. ``required_aegis_version`` semver matching) is **not** part of
R4-A's surface; that wiring lands with ticket #777. Until then, version
checking is a no-op here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from aegis.constants import AnswerKeys

from ..component_utils import extract_base_component_name
from .spec import PluginSpec


class CompatStatus(Enum):
    """Verdict from a plugin compatibility check."""

    READY = "ready"
    """All declared dependencies are satisfied; the plugin can be added."""

    IN_TREE = "in_tree"
    """The spec is an in-tree service or component, already first-party."""

    NOT_IN_PROJECT = "not_in_project"
    """The check ran outside an Aegis project; only static spec data is shown."""

    MISSING_COMPONENT = "missing_component"
    """A required component is not present in the project."""

    MISSING_SERVICE = "missing_service"
    """A required first-party service is not present in the project."""

    MISSING_PLUGIN = "missing_plugin"
    """A required external plugin is not installed."""

    CONFLICT = "conflict"
    """The plugin conflicts with something already enabled in the project."""

    ALREADY_INSTALLED = "already_installed"
    """The plugin is already recorded in the project's answers."""


@dataclass(frozen=True)
class CompatReport:
    """Outcome of ``check_compat`` for a single plugin against a project."""

    status: CompatStatus
    detail: str
    """Human-readable single-line summary suitable for a status column."""


def check_compat(
    spec: PluginSpec,
    answers: dict[str, Any] | None,
    *,
    is_in_tree: bool = False,
    discovered_plugin_names: set[str] | None = None,
) -> CompatReport:
    """Compatibility report for ``spec`` against the project at ``answers``.

    Args:
        spec: The plugin spec to evaluate.
        answers: Contents of ``.copier-answers.yml``, or ``None`` when no
            project is in scope (caller didn't pass ``--project-path`` and
            we're not inside a project).
        is_in_tree: True when this spec is one of the in-tree services or
            components (not third-party). Short-circuits the check with
            ``IN_TREE`` so the list view shows a clean "first-party"
            badge instead of a redundant "ready" verdict.
        discovered_plugin_names: Names of every external plugin currently
            discovered via ``discover_plugins()``. Used for
            ``required_plugins`` resolution. Defaults to empty.

    Returns:
        A ``CompatReport``. The order of checks is deliberate:
        in-tree → not-in-project → already-installed → conflicts →
        components → services → plugins → ready. Earlier checks short
        circuit so the most actionable verdict surfaces first.
    """
    if is_in_tree:
        return CompatReport(CompatStatus.IN_TREE, "first-party (in-tree)")

    if answers is None:
        return CompatReport(
            CompatStatus.NOT_IN_PROJECT,
            "run with --project-path or from inside a project to check compat",
        )

    discovered = discovered_plugin_names or set()
    installed_plugins = _installed_plugins(answers)

    if spec.name in installed_plugins:
        return CompatReport(
            CompatStatus.ALREADY_INSTALLED,
            "already added to this project",
        )

    # Conflicts win over missing-deps: if the plugin can't coexist, telling
    # the user "you're missing X" is misleading — they need to remove
    # something else first.
    for conflict in spec.conflicts:
        if _is_present(conflict, answers, installed_plugins):
            return CompatReport(
                CompatStatus.CONFLICT,
                f"conflicts with {conflict!r} (already enabled)",
            )

    for required in spec.required_components:
        base = extract_base_component_name(required)
        flag = AnswerKeys.include_key(base)
        if not _truthy(answers.get(flag)):
            return CompatReport(
                CompatStatus.MISSING_COMPONENT,
                f"requires component {required!r} (not enabled)",
            )

    for required in spec.required_services:
        flag = AnswerKeys.include_key(required)
        if not _truthy(answers.get(flag)):
            return CompatReport(
                CompatStatus.MISSING_SERVICE,
                f"requires service {required!r} (not enabled)",
            )

    for required_plugin in spec.required_plugins:
        # Strip any version constraint (e.g. "auth>=1.0" -> "auth") for the
        # presence check. Real semver matching is part of #777.
        plugin_name = _plugin_name_only(required_plugin)
        if plugin_name not in discovered and plugin_name not in installed_plugins:
            return CompatReport(
                CompatStatus.MISSING_PLUGIN,
                f"requires plugin {required_plugin!r} (not installed)",
            )

    return CompatReport(CompatStatus.READY, "ready to add")


# ---------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------


def _truthy(value: Any) -> bool:
    """Match the ``is_enabled`` semantics from cleanup_components.

    Both Cookiecutter (string ``"yes"``/``"no"``) and Copier (boolean
    ``True``/``False``) populate the answers file; accept both.
    """
    return value is True or value == "yes"


def _is_present(name: str, answers: dict[str, Any], plugins: set[str]) -> bool:
    """Return True if ``name`` is enabled as a component, service, or plugin."""
    base = extract_base_component_name(name)
    if _truthy(answers.get(AnswerKeys.include_key(base))):
        return True
    return name in plugins or base in plugins


def _installed_plugins(answers: dict[str, Any]) -> set[str]:
    """Pull the list of installed plugin names from the answers file.

    ``_plugins`` entries are dicts (from
    :func:`plugin_composer.serialize_plugin_to_answer`) with a ``name``
    field. Strings are accepted as a back-compat fallback for any
    pre-Round-8 ``_plugins`` legacy data still in the wild.
    """
    raw = answers.get("_plugins") or []
    if not isinstance(raw, list):
        return set()
    names: set[str] = set()
    for item in raw:
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str):
                names.add(name)
        elif isinstance(item, str):
            names.add(_plugin_name_only(item))
    return names


def _plugin_name_only(constraint: str) -> str:
    """Extract bare plugin name from a constraint like ``"auth>=1.0"``."""
    for sep in (">=", "<=", "==", "!=", ">", "<", "~="):
        if sep in constraint:
            return constraint.split(sep, 1)[0].strip()
    return constraint.strip()


def check_aegis_version_compat(
    spec: PluginSpec,
    current_aegis_version: str | None = None,
) -> tuple[bool, str]:
    """Verify ``spec.aegis_version`` is satisfied by the running CLI.

    Args:
        spec: The plugin spec being installed / updated.
        current_aegis_version: The CLI version to check against. Defaults
            to ``aegis.__version__`` so callers normally pass nothing —
            the kwarg exists for tests that need a synthetic version.

    Returns:
        ``(True, "")`` if the spec declares no constraint, or the
        constraint is satisfied. ``(False, message)`` when the running
        CLI sits outside the declared range or the constraint string
        is malformed. The message is always a populated string when
        the bool is False — callers can interpolate it directly without
        defensive ``or "..."`` fallbacks.

    The constraint is a PEP 440 specifier (``">=0.6,<0.8"``). An empty
    ``aegis_version`` is treated as "no constraint" so plugins predating
    #777 keep installing without changes.
    """
    if not spec.aegis_version:
        return (True, "")

    # Lazy import to keep ``packaging`` out of the import path for callers
    # that never reach this helper. ``packaging`` is a setuptools/pip
    # transitive dep, available everywhere aegis runs.
    from packaging.specifiers import InvalidSpecifier, SpecifierSet
    from packaging.version import InvalidVersion, Version

    if current_aegis_version is None:
        from aegis import __version__ as current_aegis_version

    try:
        spec_set = SpecifierSet(spec.aegis_version)
    except InvalidSpecifier as e:
        return (
            False,
            f"plugin {spec.name!r} declares an invalid aegis_version "
            f"specifier {spec.aegis_version!r}: {e}",
        )

    try:
        current = Version(current_aegis_version)
    except InvalidVersion as e:
        return (
            False,
            f"running aegis version {current_aegis_version!r} is not a "
            f"valid PEP 440 version: {e}",
        )

    # Pre-releases only when the constraint names one, as pip has it:
    # packaging 26 accepts them by default, so it is said here.
    if spec_set.contains(current, prereleases=bool(spec_set.prereleases)):
        return (True, "")
    return (
        False,
        f"plugin {spec.name!r} requires aegis {spec.aegis_version}, "
        f"but the running CLI is {current_aegis_version}.",
    )


def reverse_dependents(
    target_name: str,
    candidates: Iterable[Any],
    answers: dict[str, Any],
) -> list[str]:
    """Return the names of installed services / plugins that depend on
    ``target_name``.

    Used by ``aegis remove`` to refuse a destructive removal that would
    leave dangling ``required_services`` / ``required_plugins`` /
    ``required_components`` references in still-installed specs.

    Args:
        target_name: The name of the spec being removed (e.g. ``"auth"``,
            ``"scraper"``).
        candidates: Every spec that *could* be installed (typically the
            union of ``SERVICES``, ``COMPONENTS``, and discovered
            external plugins).
        answers: The project's ``.copier-answers.yml`` content.

    Returns:
        Names of currently-installed candidates whose declared
        dependencies include ``target_name``. Empty list when nothing
        depends on it (safe to remove).
    """
    plugins = _installed_plugins(answers)

    dependents: list[str] = []
    for cand in candidates:
        cand_name = getattr(cand, "name", None)
        if cand_name is None or cand_name == target_name:
            continue
        if not _is_present(cand_name, answers, plugins):
            continue

        deps: list[str] = []
        deps.extend(getattr(cand, "required_services", []) or [])
        deps.extend(getattr(cand, "required_plugins", []) or [])
        deps.extend(getattr(cand, "required_components", []) or [])

        if any(_plugin_name_only(d) == target_name for d in deps):
            dependents.append(cand_name)

    return dependents
