"""
Component file tracking infrastructure.

This module provides functionality to identify which files belong to which
components by parsing the Copier template's exclusion rules.
"""

import functools
import importlib.util
import re
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from ..constants import AnswerKeys, StorageBackends

# Constants
PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"
JINJA_EXTENSION = ".jinja"

# Tooling/cache directories and compiled artefacts that may appear in the
# template tree locally (e.g. ``__pycache__`` from importing a template's raw
# ``.py`` files). They are never authored template content, and the downstream
# renderer reads files as UTF-8 text, so a stray ``.pyc`` crashes the walk.
_SKIP_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})
_COMPILED_SUFFIXES = frozenset({".pyc", ".pyo", ".pyd"})
# Images, fonts and archives: authored, but not UTF-8 text, so they are copied
# and never rendered.
_BINARY_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".webp",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".pdf",
        ".zip",
        ".gz",
    }
)


def _is_tooling_file(file_path: Path) -> bool:
    """True for tooling-cache and compiled files: no part of any template."""
    if any(part in _SKIP_DIRS for part in file_path.parts):
        return True
    return file_path.suffix.lower() in _COMPILED_SUFFIXES


def is_binary_asset(file_path: Path | str) -> bool:
    """True for a file that is copied byte for byte, never rendered."""
    return Path(file_path).suffix.lower() in _BINARY_SUFFIXES


def get_template_path() -> Path:
    """Get path to Copier template directory."""
    return Path(__file__).parent.parent / "templates" / "copier-aegis-project"


def template_module(name: str, *parts: str) -> ModuleType:
    """A module of the generated app (``parts`` under the project, its
    imports the standard library's only), loaded from the template this
    CLI ships: the CLI reads the app's one copy instead of keeping its own."""
    path = get_template_path() / PROJECT_SLUG_PLACEHOLDER
    spec = importlib.util.spec_from_file_location(name, path.joinpath(*parts))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_copier_config() -> dict[str, Any]:
    """
    Load copier.yml configuration.

    Returns:
        Dictionary containing Copier template configuration

    Raises:
        FileNotFoundError: If copier.yml doesn't exist
        yaml.YAMLError: If copier.yml is invalid
    """
    # copier.yml is now at repo root (aegis-stack/copier.yml)
    # not in the template subdirectory
    repo_root = Path(__file__).parent.parent.parent
    copier_yml = repo_root / "copier.yml"

    if not copier_yml.exists():
        raise FileNotFoundError(f"copier.yml not found at {copier_yml}")

    try:
        with open(copier_yml) as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Failed to parse copier.yml: {e}") from e


def get_copier_defaults() -> dict[str, Any]:
    """
    Extract default values for all template variables from copier.yml.

    Used by ManualUpdater to backfill missing answer keys before rendering
    templates. Without this, undefined variables like ``ollama_mode`` cause
    Jinja2 conditionals to inject unrelated component code (#504).

    Returns:
        Dictionary mapping variable names to their default values.
        Skips Jinja2-expression defaults (they depend on other variables).
        Returns empty dict if copier.yml is not available (e.g. pip install).
    """
    try:
        config = load_copier_config()
    except FileNotFoundError:
        # copier.yml lives at repo root, not inside the aegis/ package.
        # When installed via pip/uvx the file won't exist — fall back
        # gracefully so ManualUpdater behaves the same as before this fix.
        return {}

    defaults: dict[str, Any] = {}

    for key, value in config.items():
        # Skip private/internal Copier keys (e.g. _min_copier_version)
        if key.startswith("_"):
            continue

        if isinstance(value, dict) and "default" in value:
            default = value["default"]
            # Skip Jinja2 expression defaults — they depend on other variables
            # and the answers file should already have them when relevant
            if isinstance(default, str) and "{{" in default:
                continue
            defaults[key] = default

    return defaults


def parse_exclusion_pattern(pattern: str, component: str) -> str | None:
    """
    Parse a Jinja2 exclusion pattern to extract the file path for a component.

    Args:
        pattern: Jinja2 pattern like "{% if not include_scheduler %}path/to/file{% endif %}"
        component: Component name to match (e.g., "scheduler", "worker")

    Returns:
        Extracted file path, or None if pattern doesn't match the component

    Examples:
        >>> parse_exclusion_pattern(
        ...     "{% if not include_scheduler %}{{ project_slug }}/app/components/scheduler{% endif %}",
        ...     "scheduler"
        ... )
        "app/components/scheduler"

        >>> parse_exclusion_pattern(
        ...     "{% if scheduler_backend == 'memory' -%}{{ project_slug }}/app/services/scheduler{% endif %}",
        ...     "scheduler"
        ... )
        "app/services/scheduler"
    """
    # Check if pattern references this component
    if f"include_{component}" not in pattern and component not in pattern:
        return None

    # Extract path from pattern
    # Patterns look like: "{% if condition %}{{ project_slug }}/path/to/file{% endif %}"
    # We want to extract: "path/to/file"

    # Match: {% if ... %}...{{ project_slug }}/PATH{% endif %}
    match = re.search(
        r"\{%\s*if\s+.+?\s*%\}\{\{\s*project_slug\s*\}\}/(.+?)\{%\s*endif\s*%\}",
        pattern,
    )

    if match:
        # Remove any trailing wildcards or special characters
        path = match.group(1).rstrip("*")
        return path

    return None


def _expand_directories_to_files(paths: list[str]) -> list[str]:
    """
    Expand directory paths to include all nested files.

    The template tree does not change while aegis runs, so one walk per
    list is kept (an add asks for the same groups for every installed spec).

    For each directory path, recursively discover all files within it
    by scanning the template directory.

    Args:
        paths: List of file/directory paths (e.g., ["app/components/scheduler", "app/core/db.py"])

    Returns:
        Expanded list with all nested files discovered

    Example:
        >>> _expand_directories_to_files(["app/components/scheduler"])
        ["app/components/scheduler/__init__.py", "app/components/scheduler/main.py"]
    """
    return list(_expand(tuple(paths)))


@functools.cache
def _expand(paths: tuple[str, ...]) -> tuple[str, ...]:
    template_path = get_template_path()
    expanded_paths: list[str] = []

    for path in paths:
        # Full path in template: template/{{ project_slug }}/path
        template_dir = template_path / PROJECT_SLUG_PLACEHOLDER / path

        if template_dir.exists() and template_dir.is_dir():
            # Recursively find all files in this directory
            for file_path in template_dir.rglob("*"):
                if file_path.is_file() and not _is_tooling_file(file_path):
                    # Convert back to relative path
                    # /path/to/template/{{ project_slug }}/app/components/scheduler/main.py.jinja
                    # -> app/components/scheduler/main.py.jinja
                    relative_path = file_path.relative_to(
                        template_path / PROJECT_SLUG_PLACEHOLDER
                    )

                    # Remove .jinja extension for the final path
                    path_str = str(relative_path)
                    if path_str.endswith(JINJA_EXTENSION):
                        path_str = path_str[: -len(JINJA_EXTENSION)]

                    expanded_paths.append(path_str)
        else:
            # Not a directory or doesn't exist - keep as-is (it's a file path)
            expanded_paths.append(path)

    return tuple(expanded_paths)


def _spec_extras(component: str) -> dict[str, list[str]]:
    """Return the ``extras`` groups declared on a component/service spec."""
    from .components import COMPONENTS
    from .services import SERVICES

    spec = COMPONENTS.get(component) or SERVICES.get(component)
    return spec.files.extras if spec is not None else {}


def _foreign_gated_files(component: str, answers: dict[str, Any]) -> set[str]:
    """Files another spec owns conditionally, whose condition is off.

    A spec can own files that live inside another spec's tree: auth's htmx
    login pages sit under ``app/components/web_frontend``, which the htmx
    component owns wholesale. Auth declares them in an ``include_htmx``
    extras bucket so an htmx-without-auth project does not carry them, and
    ``init`` honours that. Adding the OWNER of the tree has to honour it
    too, or the pages arrive with nothing routing to them.

    A bucket applies when its owning spec is installed and its own gate is
    truthy; anything else it lists is not the adding component's to write.
    """
    from .components import COMPONENTS
    from .services import SERVICES

    excluded: set[str] = set()
    for name, spec in {**SERVICES, **COMPONENTS}.items():
        if name == component:
            continue
        owner_installed = answers.get(AnswerKeys.include_key(name), False)
        for group, files in (spec.files.extras or {}).items():
            if owner_installed and group_on(group, answers):
                continue
            excluded |= set(_expand_directories_to_files(files))
    return excluded


def dependent_files(
    component: str, answers: dict[str, Any], *, expand: bool
) -> list[str]:
    """Files other installed specs keep only while ``component`` is there:
    their extras keyed on its flag (mcp's activity record and deploy's
    history, keyed on the database). Adding ``component`` brings them and
    removing it takes them, whichever spec owns them. ``expand`` lists a
    directory's files, for copying; unexpanded, for deleting whole."""
    from .components import COMPONENTS
    from .services import SERVICES

    specs = {**SERVICES, **COMPONENTS}
    key = AnswerKeys.include_key(component)
    paths = [
        path
        for name, spec in specs.items()
        if name != component and answers.get(AnswerKeys.include_key(name))
        for path in (spec.files.extras or {}).get(key, [])
        if _other_gates_hold(spec, key, path, answers)
    ]
    return _expand_directories_to_files(paths) if expand else paths


def _other_gates_hold(spec: Any, key: str, path: str, answers: dict[str, Any]) -> bool:
    """Whether every *other* gate on ``path`` is also enabled.

    A spec may list one file under two answer keys, meaning it needs both:
    deploy's off-site copy sits under ``include_database`` and
    ``include_scheduler``, since it is the scheduled backup sent onwards;
    ai's voice partials under ``include_htmx`` and ``ai_voice``.
    Honouring only the group that brought the file in wrote ``offsite.py``
    into a deploy stack with no scheduler, where the backup module it
    imports renders empty (aegis issue #1873).
    """
    for group, files in (spec.files.extras or {}).items():
        gates_this = group != key and path in files
        if gates_this and not group_on(group, answers):
            return False
    return True


# What a part keeps in a database: off on its memory backend.
AI_PERSISTENCE = "ai_persistence"
SCHEDULER_PERSISTENCE = "scheduler_persistence"


def _persisted(backend_key: str) -> Callable[[Mapping[str, Any]], bool]:
    return lambda answers: (
        (answers.get(backend_key) or StorageBackends.MEMORY) != StorageBackends.MEMORY
    )


# Extras groups that follow from an answer rather than being one.
DERIVED_GATES: dict[str, Callable[[Mapping[str, Any]], bool]] = {
    AI_PERSISTENCE: _persisted(AnswerKeys.AI_BACKEND),
    SCHEDULER_PERSISTENCE: _persisted(AnswerKeys.SCHEDULER_BACKEND),
}


def group_on(group: str, answers: Mapping[str, Any]) -> bool:
    """Whether an extras group's files belong in a project with ``answers``:
    its answer is on (``True``, or ``"yes"`` from an old answers file), or
    its ``DERIVED_GATES`` predicate holds."""
    derived = DERIVED_GATES.get(group)
    if derived:
        return derived(answers)
    value = answers.get(group)
    return value is True or value == "yes"


def get_component_files(
    component: str,
    *,
    full: bool = False,
    answers: dict[str, Any] | None = None,
) -> list[str]:
    """
    Get list of file paths that belong to a component.

    Derived from each spec's ``FileManifest`` via
    :func:`aegis.core.post_gen_tasks.get_component_file_mapping`, so generation
    and updates stay consistent.

    The default (``full=False``) returns the *add base*: the spec's ``primary``
    files, with each ``extras`` group in or out by ``group_on`` over
    ``answers`` (none reads every gate off). This is how ``aegis add`` copies
    option-gated files exactly when the project enables them (auth's org
    files on ``auth[org]``, the AI's tables on a database backend) and never
    writes the empty stubs they render to otherwise (issue #814).

    With ``full=True`` it returns the *complete footprint*: ``primary`` plus
    every ``extras`` group the spec owns (``ai_rag``, ``ai_voice``,
    ``scheduler_persistence``, ...). Used by ``aegis remove`` so a component is
    fully deleted regardless of which options were enabled; over-deletion is
    safe because missing paths are no-ops.

    Args:
        component: Component name (e.g., "scheduler", "worker", "database")
        full: When True, include every gated extra group (remove footprint)
        answers: Project answers the extras gates read

    Returns:
        List of file paths relative to project root

    Examples:
        >>> get_component_files("scheduler")
        ['app/components/scheduler', 'app/entrypoints/scheduler.py', ...]

        >>> get_component_files("scheduler", answers={"scheduler_backend": "sqlite"})
        ['app/services/scheduler', 'app/cli/tasks.py', ...]
    """
    from .post_gen_tasks import get_component_file_mapping

    mapping = get_component_file_mapping()
    base = mapping.get(component, []).copy()

    if full:
        # Remove path: complete footprint = primary + every gated extra group.
        for extra_files in _spec_extras(component).values():
            base.extend(extra_files)
        return sorted(set(_expand_directories_to_files(base)))

    # An extras group joins the add base when its gate is on, and is taken
    # back out when off: it may sit inside a primary directory (voice inside
    # ``app/services/ai``, persistence inside ``app/services/scheduler``),
    # which would otherwise copy it anyway. No answers reads every gate off.
    own_off: set[str] = set()
    for group, extra_files in _spec_extras(component).items():
        if group_on(group, answers or {}):
            base.extend(extra_files)
        else:
            own_off |= set(_expand_directories_to_files(extra_files))

    files = set(_expand_directories_to_files(base)) - own_off
    if answers:
        files -= _foreign_gated_files(component, answers)
    return sorted(files)


def get_component_cleanup_paths(component: str) -> list[str]:
    """Return the removal footprint with directories left as directories.

    Same paths as ``get_component_files(component, full=True)`` — primary plus
    every gated extra — but *unexpanded*. That difference matters: expanding a
    directory yields only the files the template ships, so anything the project
    grew afterwards (``__pycache__``, build output such as ``static/dist/``)
    survives and keeps the directory alive. Removal wants the whole tree gone,
    which is what generation's own cleanup does.

    Args:
        component: Component or service name.

    Returns:
        Project-relative paths, each a file or a directory.
    """
    from .post_gen_tasks import get_component_file_mapping

    paths = list(get_component_file_mapping().get(component, []))
    for extra_files in _spec_extras(component).values():
        paths.extend(extra_files)
    return sorted(set(paths))


def get_all_owned_paths() -> set[str]:
    """Union of every component's and service's complete file footprint.

    A path in this set is component/service-owned: its existence in a
    project is decided by manifest membership (``aegis add``/``remove``
    copies or deletes it as a unit), not by rendering — most
    component-exclusive files carry no inline ``{% if include_x %}`` gate
    at all, since manifest membership already decides whether they're
    copied in the first place. Directories are expanded to individual
    files, and every ``extras`` group is included regardless of options
    (``full=True``, matching the removal footprint).

    This is how the render-diff engine (``aegis.core.render_diff``)
    determines which template paths are safe for it to touch — anything
    NOT in this set — without a hand-maintained registration list: the
    boundary is derived from each spec's own ``FileManifest``, which
    already exists and already lives with that spec. See aegis-stack#918.
    """
    from .components import COMPONENTS
    from .services import SERVICES

    owned: set[str] = set()
    for name in (*COMPONENTS, *SERVICES):
        owned.update(get_component_files(name, full=True))
    return owned


def get_installed_owned_paths(answers: dict[str, Any]) -> set[str]:
    """What every spec ``answers`` installs would copy: its files with the
    options and other specs ``answers`` turns on, as ``aegis add`` does."""
    from .components import COMPONENTS, CORE_COMPONENTS
    from .services import SERVICES

    return {
        path
        for name in (*COMPONENTS, *SERVICES)
        if name in CORE_COMPONENTS or answers.get(AnswerKeys.include_key(name))
        for path in get_component_files(name, answers=answers)
    }


# Unowned by any component/service manifest (nothing claims them), but
# NOT safe for the render-diff engine to render either. A static file
# needs no entry: it renders the same at any answers, so the engine skips
# it (its existence is post-gen cleanup's and the ensure-hooks' to decide).
# Kept honest by ``tests/core/test_component_ownership.py``.
#
# ``.copier-answers.yml``: rendered by Copier itself with a special
# ``_copier_conf`` runtime context a bare Jinja render can't supply
# (``UndefinedError`` the first time the engine tries); it's also
# Copier's own bookkeeping file, not template content.
#
# ``alembic/env.py``: cross-cutting, materialized when ANY service needs
# migrations and removed when NONE do (``bootstrap_alembic`` /
# ``cleanup_components``). It branches on the database engine, so an add
# that changes the engine would create it in a project with no
# migrations; its existence is the migration bootstrap's job.
# Cross-spec files with an add-side restoration hook in ManualUpdater.
SERVICES_CARD_FILE = "app/components/frontend/dashboard/cards/services_card.py"
MIGRATION_SKILL_FILE = ".claude/skills/add-model-and-migration/SKILL.md"


def shows_services_card(answers: dict[str, Any]) -> bool:
    """Whether the dashboard imports ``ServicesCard``: the condition in
    ``cards/__init__.py.jinja``, where a plugin is a service too. Init,
    add and remove each keep ``SERVICES_CARD_FILE`` to it."""
    from .plugins.composer import PLUGINS_ANSWER_KEY
    from .services import SERVICE_ANSWER_KEYS

    has_service = any(group_on(key, answers) for key in SERVICE_ANSWER_KEYS)
    return has_service or bool(answers.get(PLUGINS_ANSWER_KEY))


_ENGINE_UNSAFE_PATHS: frozenset[str] = frozenset(
    {
        AnswerKeys.ANSWERS_FILENAME,
        "alembic/env.py",
    }
)


def get_shared_scope(all_paths: Iterable[str]) -> list[str]:
    """Restrict ``all_paths`` (typically ``RenderDiffEngine.discover_paths()``)
    to the render-diff engine's safe scope: every path no component/service
    manifest claims, minus :data:`_ENGINE_UNSAFE_PATHS`. A manifest-owned
    file whose content depends on another spec's answers (the scheduler's
    ``main.py`` on the worker) is reached by :func:`get_cross_spec_scope`.

    The single canonical scoping expression — callers (``ManualUpdater``,
    tests) use this rather than each re-deriving the set expression
    themselves. See aegis-stack#918/#919.
    """
    owned = get_all_owned_paths()
    candidates = set(all_paths)
    scope = candidates - owned
    scope -= _ENGINE_UNSAFE_PATHS
    return sorted(scope)


def get_cross_spec_scope(
    all_paths: Iterable[str],
    exists: Callable[[str], bool],
    operated: str,
    *,
    include_operated: bool = False,
) -> list[str]:
    """Other specs' owned files that are on disk, for an add/remove of ``operated``.

    A spec's files are copied once, when it is added, and never rendered
    again - so a template that branches on ANOTHER spec's flag kept its
    first render: ``add-service auth`` left ``finance/models/base.py`` with
    no owner keys (#1217) and several routers without their auth guards.
    Handing these to the render-diff engine is safe because it renders each
    one before and after the operation and touches only those whose output
    changes; the rest are no-ops. ``exists`` keeps existence manifest-owned:
    a file not on disk is never created by an unrelated operation, though
    ``exists`` may admit one an installed spec owns whose own gate this
    operation turns on.

    ``include_operated`` adds ``operated``'s own files: an option upgrade
    (``ai`` -> ``ai[voice]``) changes the answers they branch on too.
    """
    owned = get_all_owned_paths()
    if not include_operated:
        owned -= set(get_component_files(operated, full=True))
    return sorted(
        p for p in set(all_paths) & owned if p not in _ENGINE_UNSAFE_PATHS and exists(p)
    )
